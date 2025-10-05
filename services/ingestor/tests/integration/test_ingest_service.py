"""Integration tests for the main ingestion service."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from src.services.ingest_service import IngestService, ServiceMode
from src.config.settings import IngestorSettings


class TestIngestServiceIntegration:
    """Integration tests for IngestService."""
    
    @pytest.fixture
    def mock_components(self):
        """Mock all service components."""
        mocks = {}
        
        # Mock AWS client manager
        mocks['aws_client_manager'] = Mock()
        mocks['aws_client_manager'].verify_connections.return_value = {
            'kinesis': 'healthy',
            's3': 'healthy',
            'cloudwatch': 'healthy'
        }
        mocks['aws_client_manager'].ensure_streams_exist = AsyncMock(return_value=True)
        mocks['aws_client_manager'].ensure_bucket_exists = AsyncMock(return_value=True)
        
        # Mock Kinesis producer
        mocks['kinesis_producer'] = AsyncMock()
        mocks['kinesis_producer'].start = AsyncMock()
        mocks['kinesis_producer'].stop = AsyncMock()
        mocks['kinesis_producer'].health_check = AsyncMock(return_value={
            'status': 'healthy',
            'issues': [],
            'stats': {}
        })
        
        # Mock S3 writer
        mocks['s3_writer'] = AsyncMock()
        mocks['s3_writer'].flush_all_buffers = AsyncMock()
        mocks['s3_writer'].health_check = AsyncMock(return_value={
            'status': 'healthy',
            'issues': [],
            'stats': {}
        })
        
        # Mock SBE client
        mocks['sbe_client'] = AsyncMock()
        mocks['sbe_client'].connect = AsyncMock()
        mocks['sbe_client'].disconnect = AsyncMock()
        mocks['sbe_client'].start_streaming = AsyncMock()
        mocks['sbe_client'].health_check = AsyncMock(return_value={
            'status': 'healthy',
            'issues': [],
            'stats': {}
        })
        mocks['sbe_client']._message_handlers = {}
        
        # Mock REST client
        mocks['rest_client'] = AsyncMock()
        mocks['rest_client'].__aenter__ = AsyncMock(return_value=mocks['rest_client'])
        mocks['rest_client'].__aexit__ = AsyncMock(return_value=None)
        mocks['rest_client'].backfill_agg_trades = AsyncMock()
        
        return mocks
    
    @pytest.mark.asyncio
    async def test_sbe_mode_initialization(self, test_config, mock_components):
        """Test service initialization in SBE mode."""
        test_config.mode = "sbe"
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    service = IngestService(test_config)
                    
                    # Start service briefly to test initialization
                    start_task = asyncio.create_task(service.start())
                    await asyncio.sleep(0.1)  # Let initialization run
                    
                    # Stop service
                    service.shutdown_event.set()
                    await start_task
                    
                    # Verify components were initialized
                    assert service.kinesis_producer is not None
                    assert service.sbe_client is not None
                    assert service.s3_writer is None  # Not used in SBE mode
                    assert service.rest_client is None  # Not used in SBE mode
    
    @pytest.mark.asyncio
    async def test_rest_mode_initialization(self, test_config, mock_components):
        """Test service initialization in REST mode."""
        test_config.mode = "rest"
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.S3BronzeWriter', return_value=mock_components['s3_writer']):
                with patch('src.services.ingest_service.BinanceRESTClient', return_value=mock_components['rest_client']):
                    
                    service = IngestService(test_config)
                    
                    # Start service briefly
                    start_task = asyncio.create_task(service.start())
                    await asyncio.sleep(0.1)
                    
                    # Stop service
                    service.shutdown_event.set()
                    await start_task
                    
                    # Verify components were initialized
                    assert service.s3_writer is not None
                    assert service.rest_client is not None
                    assert service.kinesis_producer is None  # Not used in REST mode
                    assert service.sbe_client is None  # Not used in REST mode
    
    @pytest.mark.asyncio
    async def test_both_mode_initialization(self, test_config, mock_components):
        """Test service initialization in BOTH mode."""
        test_config.mode = "both"
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.S3BronzeWriter', return_value=mock_components['s3_writer']):
                    with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                        with patch('src.services.ingest_service.BinanceRESTClient', return_value=mock_components['rest_client']):
                            
                            service = IngestService(test_config)
                            
                            # Start service briefly
                            start_task = asyncio.create_task(service.start())
                            await asyncio.sleep(0.1)
                            
                            # Stop service
                            service.shutdown_event.set()
                            await start_task
                            
                            # Verify all components were initialized
                            assert service.kinesis_producer is not None
                            assert service.s3_writer is not None
                            assert service.sbe_client is not None
                            assert service.rest_client is not None
    
    @pytest.mark.asyncio
    async def test_aws_connection_verification(self, test_config, mock_components):
        """Test AWS connection verification during startup."""
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            service = IngestService(test_config)
            
            # Test successful verification
            await service._verify_aws_connections()
            
            mock_components['aws_client_manager'].verify_connections.assert_called_once()
            mock_components['aws_client_manager'].ensure_streams_exist.assert_called_once()
            mock_components['aws_client_manager'].ensure_bucket_exists.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_aws_connection_failure(self, test_config, mock_components):
        """Test handling of AWS connection failures."""
        # Mock connection failure
        mock_components['aws_client_manager'].verify_connections.return_value = {
            'kinesis': 'error: connection failed',
            's3': 'healthy',
            'cloudwatch': 'healthy'
        }
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            service = IngestService(test_config)
            
            with pytest.raises(RuntimeError, match="AWS kinesis connection failed"):
                await service._verify_aws_connections()
    
    @pytest.mark.asyncio
    async def test_service_stats_collection(self, test_config, mock_components):
        """Test service statistics collection."""
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    # Mock stats returns
                    mock_components['sbe_client'].get_stats.return_value = {
                        'messages_received': 100,
                        'is_connected': True
                    }
                    mock_components['kinesis_producer'].get_stats.return_value = {
                        'overall': {'total_records': 50}
                    }
                    
                    service = IngestService(test_config)
                    await service._initialize_components()
                    
                    stats = service.get_stats()
                    
                    assert 'service' in stats
                    assert 'sbe_client' in stats
                    assert 'kinesis_producer' in stats
                    
                    # Check service-level stats
                    service_stats = stats['service']
                    assert 'mode' in service_stats
                    assert 'uptime_seconds' in service_stats
                    assert 'running' in service_stats
    
    @pytest.mark.asyncio
    async def test_health_check_integration(self, test_config, mock_components):
        """Test integrated health check across all components."""
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    service = IngestService(test_config)
                    await service._initialize_components()
                    service.running = True
                    
                    health = await service.health_check()
                    
                    assert 'status' in health
                    assert 'overall' in health
                    assert 'components' in health
                    assert 'stats' in health
                    
                    # Verify component health checks were called
                    mock_components['sbe_client'].health_check.assert_called_once()
                    mock_components['kinesis_producer'].health_check.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, test_config, mock_components):
        """Test graceful service shutdown."""
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    service = IngestService(test_config)
                    await service._initialize_components()
                    
                    # Simulate running state
                    service.running = True
                    
                    # Stop service
                    await service.stop()
                    
                    # Verify components were stopped
                    mock_components['kinesis_producer'].stop.assert_called_once()
                    mock_components['sbe_client'].disconnect.assert_called_once()
                    
                    assert service.running is False
    
    @pytest.mark.asyncio
    async def test_sbe_message_handling(self, test_config, mock_components, sample_trade_data):
        """Test SBE message processing integration."""
        from src.clients.binance_sbe import SBEMessage, SBEMessageType
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    service = IngestService(test_config)
                    await service._initialize_components()
                    
                    # Create test SBE message
                    sbe_message = SBEMessage(
                        message_type=SBEMessageType.TRADE,
                        symbol="BTCUSDT",
                        event_time=1640995200000,
                        data=sample_trade_data,
                        raw_message="{}"
                    )
                    
                    # Process message
                    await service._process_sbe_message(sbe_message)
                    
                    # Verify Kinesis producer was called
                    mock_components['kinesis_producer'].put_trade_record.assert_called_once_with(sample_trade_data)
    
    @pytest.mark.asyncio
    async def test_error_handling_in_message_processing(self, test_config, mock_components, sample_trade_data):
        """Test error handling during message processing."""
        from src.clients.binance_sbe import SBEMessage, SBEMessageType
        
        # Mock Kinesis producer to raise exception
        mock_components['kinesis_producer'].put_trade_record.side_effect = Exception("Kinesis error")
        
        with patch('src.services.ingest_service.AWSClientManager', return_value=mock_components['aws_client_manager']):
            with patch('src.services.ingest_service.KinesisProducer', return_value=mock_components['kinesis_producer']):
                with patch('src.services.ingest_service.BinanceSBEClient', return_value=mock_components['sbe_client']):
                    
                    service = IngestService(test_config)
                    await service._initialize_components()
                    
                    # Create test SBE message
                    sbe_message = SBEMessage(
                        message_type=SBEMessageType.TRADE,
                        symbol="BTCUSDT",
                        event_time=1640995200000,
                        data=sample_trade_data,
                        raw_message="{}"
                    )
                    
                    # Process message - should handle error gracefully
                    await service._process_sbe_message(sbe_message)
                    
                    # Error should be recorded in stats
                    assert service.stats.errors > 0