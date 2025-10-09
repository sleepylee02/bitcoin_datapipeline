"""AWS-specific configuration and client setup."""

import boto3
from botocore.config import Config
from typing import Optional
import logging

from .settings import AWSConfig

logger = logging.getLogger(__name__)


class AWSClientManager:
    """Manages AWS client instances with proper configuration."""
    
    def __init__(self, aws_config: AWSConfig):
        self.config = aws_config
        self._kinesis_client = None
        self._s3_client = None
        self._cloudwatch_client = None
        
        # Configure boto3 with retry and timeout settings
        self._boto_config = Config(
            region_name=aws_config.region,
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            },
            max_pool_connections=50,
            connect_timeout=10,
            read_timeout=30
        )
    
    @property
    def kinesis_client(self):
        """Get or create Kinesis client."""
        if self._kinesis_client is None:
            if self.config.localstack_endpoint:
                # LocalStack configuration for local development
                self._kinesis_client = boto3.client(
                    'kinesis',
                    endpoint_url=self.config.localstack_endpoint,
                    aws_access_key_id='test',
                    aws_secret_access_key='test',
                    region_name=self.config.region
                )
                logger.info(f"Created LocalStack Kinesis client: {self.config.localstack_endpoint}")
            else:
                # Production AWS configuration
                self._kinesis_client = boto3.client(
                    'kinesis',
                    config=self._boto_config
                )
                logger.info(f"Created AWS Kinesis client in region: {self.config.region}")
        
        return self._kinesis_client
    
    @property
    def s3_client(self):
        """Get or create S3 client."""
        if self._s3_client is None:
            if self.config.localstack_endpoint:
                # LocalStack configuration
                self._s3_client = boto3.client(
                    's3',
                    endpoint_url=self.config.localstack_endpoint,
                    aws_access_key_id='test',
                    aws_secret_access_key='test',
                    region_name=self.config.region
                )
                logger.info(f"Created LocalStack S3 client: {self.config.localstack_endpoint}")
            else:
                # Production AWS configuration
                self._s3_client = boto3.client(
                    's3',
                    config=self._boto_config
                )
                logger.info(f"Created AWS S3 client in region: {self.config.region}")
        
        return self._s3_client
    
    @property
    def cloudwatch_client(self):
        """Get or create CloudWatch client."""
        if self._cloudwatch_client is None:
            if self.config.localstack_endpoint:
                # LocalStack configuration
                self._cloudwatch_client = boto3.client(
                    'cloudwatch',
                    endpoint_url=self.config.localstack_endpoint,
                    aws_access_key_id='test',
                    aws_secret_access_key='test',
                    region_name=self.config.region
                )
                logger.info(f"Created LocalStack CloudWatch client: {self.config.localstack_endpoint}")
            else:
                # Production AWS configuration
                self._cloudwatch_client = boto3.client(
                    'cloudwatch',
                    config=self._boto_config
                )
                logger.info(f"Created AWS CloudWatch client in region: {self.config.region}")
        
        return self._cloudwatch_client
    
    def verify_connections(self) -> dict:
        """Verify AWS service connections and return status."""
        status = {}
        
        try:
            # Test Kinesis connection
            self.kinesis_client.list_streams(Limit=1)
            status['kinesis'] = 'healthy'
            logger.info("Kinesis connection verified")
        except Exception as e:
            status['kinesis'] = f'error: {str(e)}'
            logger.error(f"Kinesis connection failed: {e}")
        
        try:
            # Test S3 connection
            self.s3_client.list_buckets()
            status['s3'] = 'healthy'
            logger.info("S3 connection verified")
        except Exception as e:
            status['s3'] = f'error: {str(e)}'
            logger.error(f"S3 connection failed: {e}")
        
        try:
            # Test CloudWatch connection
            self.cloudwatch_client.list_metrics(MaxRecords=1)
            status['cloudwatch'] = 'healthy'
            logger.info("CloudWatch connection verified")
        except Exception as e:
            status['cloudwatch'] = f'error: {str(e)}'
            logger.error(f"CloudWatch connection failed: {e}")
        
        return status
    
    async def ensure_streams_exist(self) -> bool:
        """Ensure required Kinesis streams exist."""
        streams_to_check = [
            self.config.kinesis_trade_stream,
            self.config.kinesis_bba_stream,
            self.config.kinesis_depth_stream
        ]
        
        try:
            existing_streams = self.kinesis_client.list_streams()['StreamNames']
            
            for stream_name in streams_to_check:
                if stream_name not in existing_streams:
                    logger.warning(f"Stream {stream_name} does not exist")
                    if self.config.localstack_endpoint:
                        # Create stream in LocalStack for development
                        self.kinesis_client.create_stream(
                            StreamName=stream_name,
                            ShardCount=1
                        )
                        logger.info(f"Created stream {stream_name} in LocalStack")
                    else:
                        # In production, streams should be created via Terraform
                        logger.error(f"Stream {stream_name} missing in production")
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify streams: {e}")
            return False
    
    async def ensure_bucket_exists(self) -> bool:
        """Ensure S3 bucket exists and is accessible."""
        try:
            self.s3_client.head_bucket(Bucket=self.config.s3_bucket)
            logger.info(f"S3 bucket {self.config.s3_bucket} verified")
            return True
        except Exception as e:
            if self.config.localstack_endpoint:
                # Create bucket in LocalStack
                try:
                    self.s3_client.create_bucket(Bucket=self.config.s3_bucket)
                    logger.info(f"Created S3 bucket {self.config.s3_bucket} in LocalStack")
                    return True
                except Exception as create_error:
                    logger.error(f"Failed to create bucket in LocalStack: {create_error}")
                    return False
            else:
                logger.error(f"S3 bucket {self.config.s3_bucket} not accessible: {e}")
                return False