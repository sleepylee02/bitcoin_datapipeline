"""Metrics service for monitoring and observability."""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

from prometheus_client import Counter, Histogram, Gauge, start_http_server
import boto3

from ..config.settings import MetricsConfig

logger = logging.getLogger(__name__)


class MetricsService:
    """
    Metrics collection and emission service.
    
    Supports:
    - Prometheus metrics (for local monitoring)
    - CloudWatch metrics (for AWS monitoring)
    """
    
    def __init__(self, config: MetricsConfig, ingest_service):
        self.config = config
        self.ingest_service = ingest_service
        
        # Prometheus metrics
        self.prometheus_server = None
        self.prometheus_task: Optional[asyncio.Task] = None
        
        # CloudWatch client
        self.cloudwatch_client = None
        self.cloudwatch_task: Optional[asyncio.Task] = None
        
        # Initialize Prometheus metrics if enabled
        if self.config.enable_prometheus:
            self._init_prometheus_metrics()
        
        # Initialize CloudWatch client if enabled
        if self.config.enable_cloudwatch:
            self._init_cloudwatch_client()
        
        logger.info("MetricsService initialized")
    
    def _init_prometheus_metrics(self):
        """Initialize Prometheus metrics."""
        
        # Define metrics
        self.prom_messages_total = Counter(
            'ingestor_messages_total',
            'Total number of messages processed',
            ['source', 'symbol', 'message_type']
        )
        
        self.prom_processing_duration = Histogram(
            'ingestor_processing_duration_seconds',
            'Time spent processing messages',
            ['operation']
        )
        
        self.prom_errors_total = Counter(
            'ingestor_errors_total',
            'Total number of errors',
            ['component', 'error_type']
        )
        
        self.prom_kinesis_records = Counter(
            'ingestor_kinesis_records_total',
            'Total records sent to Kinesis',
            ['stream']
        )
        
        self.prom_s3_files = Counter(
            'ingestor_s3_files_total',
            'Total files written to S3',
            ['data_type']
        )
        
        self.prom_connection_status = Gauge(
            'ingestor_connection_status',
            'Connection status (1=connected, 0=disconnected)',
            ['component']
        )
        
        self.prom_queue_size = Gauge(
            'ingestor_queue_size',
            'Current queue size',
            ['queue_type']
        )
        
        self.prom_last_message_timestamp = Gauge(
            'ingestor_last_message_timestamp',
            'Timestamp of last processed message',
            ['source']
        )
        
        logger.info("Prometheus metrics initialized")
    
    def _init_cloudwatch_client(self):
        """Initialize CloudWatch client."""
        try:
            self.cloudwatch_client = boto3.client('cloudwatch')
            logger.info("CloudWatch client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize CloudWatch client: {e}")
            self.cloudwatch_client = None
    
    async def start(self):
        """Start the metrics services."""
        tasks = []
        
        # Start Prometheus server if enabled
        if self.config.enable_prometheus:
            try:
                start_http_server(self.config.prometheus_port)
                logger.info(f"Prometheus metrics server started on port {self.config.prometheus_port}")
                
                # Start metrics collection task
                self.prometheus_task = asyncio.create_task(self._prometheus_collection_loop())
                tasks.append(self.prometheus_task)
                
            except Exception as e:
                logger.error(f"Failed to start Prometheus server: {e}")
        
        # Start CloudWatch metrics if enabled
        if self.config.enable_cloudwatch and self.cloudwatch_client:
            self.cloudwatch_task = asyncio.create_task(self._cloudwatch_emission_loop())
            tasks.append(self.cloudwatch_task)
        
        logger.info("MetricsService started")
    
    async def stop(self):
        """Stop the metrics services."""
        
        # Cancel tasks
        for task in [self.prometheus_task, self.cloudwatch_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("MetricsService stopped")
    
    async def _prometheus_collection_loop(self):
        """Background loop for updating Prometheus metrics."""
        
        while True:
            try:
                await asyncio.sleep(10)  # Update every 10 seconds
                
                # Get service stats
                stats = self.ingest_service.get_stats()
                
                # Update connection status metrics
                if 'sbe_client' in stats:
                    sbe_stats = stats['sbe_client']
                    self.prom_connection_status.labels(component='sbe').set(
                        1 if sbe_stats.get('is_connected', False) else 0
                    )
                    
                    # Update last message timestamp
                    if sbe_stats.get('last_message_time'):
                        self.prom_last_message_timestamp.labels(source='sbe').set(
                            sbe_stats['last_message_time']
                        )
                
                # Update Kinesis metrics
                if 'kinesis_producer' in stats:
                    kinesis_stats = stats['kinesis_producer']
                    
                    # Queue sizes
                    for stream, queue_size in kinesis_stats['overall'].get('queue_sizes', {}).items():
                        self.prom_queue_size.labels(queue_type=f'kinesis_{stream}').set(queue_size)
                
                # Update S3 metrics
                if 's3_writer' in stats:
                    s3_stats = stats['s3_writer']
                    # S3 metrics are cumulative, so we just track them
                
                logger.debug("Prometheus metrics updated")
                
            except Exception as e:
                logger.error(f"Error updating Prometheus metrics: {e}")
                await asyncio.sleep(5)
    
    async def _cloudwatch_emission_loop(self):
        """Background loop for emitting CloudWatch metrics."""
        
        while True:
            try:
                await asyncio.sleep(60)  # Emit every minute
                
                # Get service stats
                stats = self.ingest_service.get_stats()
                
                # Prepare CloudWatch metrics
                metrics = self._prepare_cloudwatch_metrics(stats)
                
                if metrics:
                    # Send metrics to CloudWatch
                    await self._emit_cloudwatch_metrics(metrics)
                
                logger.debug("CloudWatch metrics emitted")
                
            except Exception as e:
                logger.error(f"Error emitting CloudWatch metrics: {e}")
                await asyncio.sleep(30)
    
    def _prepare_cloudwatch_metrics(self, stats: Dict[str, Any]) -> list:
        """Prepare CloudWatch metrics from service stats."""
        
        metrics = []
        timestamp = datetime.utcnow()
        
        # Service-level metrics
        service_stats = stats.get('service', {})
        
        metrics.extend([
            {
                'MetricName': 'MessagesProcessed',
                'Value': service_stats.get('messages_processed', 0),
                'Unit': 'Count',
                'Timestamp': timestamp
            },
            {
                'MetricName': 'RecordsWrittenS3',
                'Value': service_stats.get('records_written_s3', 0),
                'Unit': 'Count',
                'Timestamp': timestamp
            },
            {
                'MetricName': 'RecordsSentKinesis',
                'Value': service_stats.get('records_sent_kinesis', 0),
                'Unit': 'Count',
                'Timestamp': timestamp
            },
            {
                'MetricName': 'Errors',
                'Value': service_stats.get('errors', 0),
                'Unit': 'Count',
                'Timestamp': timestamp
            },
            {
                'MetricName': 'ServiceRunning',
                'Value': 1 if service_stats.get('running', False) else 0,
                'Unit': 'Count',
                'Timestamp': timestamp
            }
        ])
        
        # SBE client metrics
        if 'sbe_client' in stats:
            sbe_stats = stats['sbe_client']
            
            metrics.extend([
                {
                    'MetricName': 'SBEMessagesReceived',
                    'Value': sbe_stats.get('messages_received', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'SBEDecodeErrors',
                    'Value': sbe_stats.get('decode_errors', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'SBEConnectionStatus',
                    'Value': 1 if sbe_stats.get('is_connected', False) else 0,
                    'Unit': 'Count',
                    'Timestamp': timestamp
                }
            ])
            
            # Last message age
            if sbe_stats.get('last_message_age_seconds') is not None:
                metrics.append({
                    'MetricName': 'SBELastMessageAge',
                    'Value': sbe_stats['last_message_age_seconds'],
                    'Unit': 'Seconds',
                    'Timestamp': timestamp
                })
        
        # Kinesis producer metrics
        if 'kinesis_producer' in stats:
            kinesis_stats = stats['kinesis_producer']['overall']
            
            metrics.extend([
                {
                    'MetricName': 'KinesisTotalRecords',
                    'Value': kinesis_stats.get('total_records', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'KinesisFailedRecords',
                    'Value': kinesis_stats.get('failed_records', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'KinesisBatchesSent',
                    'Value': kinesis_stats.get('batches_sent', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                }
            ])
        
        # S3 writer metrics
        if 's3_writer' in stats:
            s3_stats = stats['s3_writer']
            
            metrics.extend([
                {
                    'MetricName': 'S3FilesWritten',
                    'Value': s3_stats.get('files_written', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'S3RecordsWritten',
                    'Value': s3_stats.get('records_written', 0),
                    'Unit': 'Count',
                    'Timestamp': timestamp
                },
                {
                    'MetricName': 'S3BytesWritten',
                    'Value': s3_stats.get('bytes_written', 0),
                    'Unit': 'Bytes',
                    'Timestamp': timestamp
                }
            ])
        
        return metrics
    
    async def _emit_cloudwatch_metrics(self, metrics: list):
        """Emit metrics to CloudWatch."""
        
        if not self.cloudwatch_client:
            return
        
        try:
            # CloudWatch has limits on batch size, so chunk the metrics
            chunk_size = 20
            for i in range(0, len(metrics), chunk_size):
                chunk = metrics[i:i + chunk_size]
                
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.cloudwatch_client.put_metric_data(
                        Namespace=self.config.metrics_namespace,
                        MetricData=chunk
                    )
                )
            
            logger.debug(f"Emitted {len(metrics)} metrics to CloudWatch")
            
        except Exception as e:
            logger.error(f"Failed to emit CloudWatch metrics: {e}")
    
    def record_message_processed(self, source: str, symbol: str, message_type: str):
        """Record a processed message."""
        if self.config.enable_prometheus:
            self.prom_messages_total.labels(
                source=source,
                symbol=symbol,
                message_type=message_type
            ).inc()
    
    def record_processing_time(self, operation: str, duration_seconds: float):
        """Record processing time."""
        if self.config.enable_prometheus:
            self.prom_processing_duration.labels(operation=operation).observe(duration_seconds)
    
    def record_error(self, component: str, error_type: str):
        """Record an error."""
        if self.config.enable_prometheus:
            self.prom_errors_total.labels(
                component=component,
                error_type=error_type
            ).inc()
    
    def record_kinesis_record(self, stream: str):
        """Record a Kinesis record sent."""
        if self.config.enable_prometheus:
            self.prom_kinesis_records.labels(stream=stream).inc()
    
    def record_s3_file(self, data_type: str):
        """Record an S3 file written."""
        if self.config.enable_prometheus:
            self.prom_s3_files.labels(data_type=data_type).inc()