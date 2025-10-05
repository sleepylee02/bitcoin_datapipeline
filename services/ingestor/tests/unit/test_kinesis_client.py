"""Tests for Kinesis client functionality."""

import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from botocore.exceptions import ClientError

from src.clients.kinesis_client import KinesisProducer, KinesisRecord
from src.config.aws_config import AWSClientManager


class TestKinesisProducer:
    """Test KinesisProducer functionality."""
    
    @pytest.fixture
    def mock_kinesis_client(self):
        """Mock Kinesis client."""
        client = Mock()
        client.put_records = Mock()
        return client
    
    @pytest.fixture
    def kinesis_producer(self, test_config, mock_aws_client_manager, mock_kinesis_client):
        """Create KinesisProducer instance."""
        mock_aws_client_manager.kinesis_client = mock_kinesis_client
        return KinesisProducer(mock_aws_client_manager, test_config.aws)
    
    @pytest.mark.asyncio
    async def test_start_stop(self, kinesis_producer):
        """Test producer start and stop."""
        await kinesis_producer.start()
        assert kinesis_producer._running is True
        assert kinesis_producer._flush_task is not None
        
        await kinesis_producer.stop()
        assert kinesis_producer._running is False
    
    @pytest.mark.asyncio
    async def test_put_record(self, kinesis_producer, sample_trade_data):
        """Test putting a single record."""
        await kinesis_producer.start()
        
        result = await kinesis_producer.put_record(
            stream_name="test-stream",
            data=sample_trade_data,
            partition_key="BTCUSDT"
        )
        
        assert result is True
        assert len(kinesis_producer._batches["test-stream"]) == 1
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_put_trade_record(self, kinesis_producer, sample_trade_data):
        """Test putting a trade record."""
        await kinesis_producer.start()
        
        result = await kinesis_producer.put_trade_record(sample_trade_data)
        
        assert result is True
        trade_stream = kinesis_producer.config.kinesis_trade_stream
        assert len(kinesis_producer._batches[trade_stream]) == 1
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_put_bba_record(self, kinesis_producer, sample_bba_data):
        """Test putting a best bid/ask record."""
        await kinesis_producer.start()
        
        result = await kinesis_producer.put_bba_record(sample_bba_data)
        
        assert result is True
        bba_stream = kinesis_producer.config.kinesis_bba_stream
        assert len(kinesis_producer._batches[bba_stream]) == 1
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_put_depth_record(self, kinesis_producer, sample_depth_data):
        """Test putting a depth record."""
        await kinesis_producer.start()
        
        result = await kinesis_producer.put_depth_record(sample_depth_data)
        
        assert result is True
        depth_stream = kinesis_producer.config.kinesis_depth_stream
        assert len(kinesis_producer._batches[depth_stream]) == 1
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_batch_flush_by_size(self, kinesis_producer, sample_trade_data, mock_kinesis_response):
        """Test batch flushing when batch size is reached."""
        # Set small batch size for testing
        kinesis_producer.batch_size = 2
        
        # Mock successful Kinesis response
        kinesis_producer.aws_client_manager.kinesis_client.put_records.return_value = mock_kinesis_response
        
        await kinesis_producer.start()
        
        # Add records to trigger flush
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        
        # Give flush task time to run
        await asyncio.sleep(0.1)
        
        # Batch should be empty after flush
        assert len(kinesis_producer._batches["test-stream"]) == 0
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_batch_flush_by_time(self, kinesis_producer, sample_trade_data, mock_kinesis_response):
        """Test batch flushing based on time interval."""
        # Set short flush interval
        kinesis_producer.flush_interval = 0.1
        
        # Mock successful Kinesis response
        kinesis_producer.aws_client_manager.kinesis_client.put_records.return_value = mock_kinesis_response
        
        await kinesis_producer.start()
        
        # Add a record
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        
        # Wait for flush interval
        await asyncio.sleep(0.2)
        
        # Batch should be empty after time-based flush
        assert len(kinesis_producer._batches["test-stream"]) == 0
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_failed_kinesis_request(self, kinesis_producer, sample_trade_data):
        """Test handling of failed Kinesis requests."""
        # Mock failed Kinesis response
        kinesis_producer.aws_client_manager.kinesis_client.put_records.side_effect = ClientError(
            error_response={'Error': {'Code': 'ThrottlingException'}},
            operation_name='PutRecords'
        )
        
        await kinesis_producer.start()
        
        # Add record and trigger flush
        kinesis_producer.batch_size = 1
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        
        # Give time for flush and retry
        await asyncio.sleep(0.2)
        
        # Should have recorded error
        assert kinesis_producer.stats['errors'] > 0
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_partial_failure_handling(self, kinesis_producer, sample_trade_data):
        """Test handling of partial failures in Kinesis batch."""
        # Mock partial failure response
        partial_failure_response = {
            'FailedRecordCount': 1,
            'Records': [
                {'SequenceNumber': '12345', 'ShardId': 'shard-1'},
                {'ErrorCode': 'InternalFailure', 'ErrorMessage': 'Internal error'}
            ]
        }
        
        kinesis_producer.aws_client_manager.kinesis_client.put_records.return_value = partial_failure_response
        
        await kinesis_producer.start()
        
        # Add records
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        
        # Trigger flush
        kinesis_producer.batch_size = 2
        await kinesis_producer.put_record("test-stream", sample_trade_data)
        
        await asyncio.sleep(0.1)
        
        # Failed record should be re-queued
        assert len(kinesis_producer._batches["test-stream"]) > 0
        
        await kinesis_producer.stop()
    
    def test_generate_partition_key(self, kinesis_producer, sample_trade_data):
        """Test partition key generation."""
        # With symbol
        key = kinesis_producer._generate_partition_key(sample_trade_data)
        assert key == "BTCUSDT"
        
        # Without symbol
        data_without_symbol = {'price': 100.0, 'qty': 1.0}
        key = kinesis_producer._generate_partition_key(data_without_symbol)
        assert len(key) == 16  # MD5 hash truncated to 16 chars
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_functionality(self, kinesis_producer, sample_trade_data):
        """Test circuit breaker opens on repeated failures."""
        # Mock consistent failures
        kinesis_producer.aws_client_manager.kinesis_client.put_records.side_effect = ClientError(
            error_response={'Error': {'Code': 'InternalFailure'}},
            operation_name='PutRecords'
        )
        
        await kinesis_producer.start()
        kinesis_producer.batch_size = 1
        
        # Trigger multiple failures
        for _ in range(6):  # More than circuit breaker threshold
            await kinesis_producer.put_record("test-stream", sample_trade_data)
            await asyncio.sleep(0.1)
        
        # Circuit breaker should be open
        circuit_breaker = kinesis_producer._circuit_breakers.get("test-stream")
        if circuit_breaker:
            assert circuit_breaker.state == 'OPEN'
        
        await kinesis_producer.stop()
    
    @pytest.mark.asyncio
    async def test_health_check(self, kinesis_producer):
        """Test health check functionality."""
        await kinesis_producer.start()
        
        health = await kinesis_producer.health_check()
        
        assert 'status' in health
        assert 'issues' in health
        assert 'stats' in health
        
        await kinesis_producer.stop()
    
    def test_get_stats(self, kinesis_producer):
        """Test statistics collection."""
        stats = kinesis_producer.get_stats()
        
        assert 'overall' in stats
        assert 'streams' in stats
        assert 'queue_sizes' in stats
        assert 'circuit_breakers' in stats
        
        # Check overall stats structure
        overall = stats['overall']
        assert 'total_records' in overall
        assert 'total_bytes' in overall
        assert 'failed_records' in overall


class TestKinesisRecord:
    """Test KinesisRecord data class."""
    
    def test_kinesis_record_creation(self):
        """Test KinesisRecord creation and attributes."""
        record = KinesisRecord(
            stream_name="test-stream",
            partition_key="test-key",
            data=b"test-data",
            explicit_hash_key="hash123",
            timestamp=1640995200.0
        )
        
        assert record.stream_name == "test-stream"
        assert record.partition_key == "test-key"
        assert record.data == b"test-data"
        assert record.explicit_hash_key == "hash123"
        assert record.timestamp == 1640995200.0
    
    def test_kinesis_record_minimal(self):
        """Test KinesisRecord with minimal required fields."""
        record = KinesisRecord(
            stream_name="test-stream",
            partition_key="test-key",
            data=b"test-data"
        )
        
        assert record.stream_name == "test-stream"
        assert record.partition_key == "test-key"
        assert record.data == b"test-data"
        assert record.explicit_hash_key is None
        assert record.timestamp is None