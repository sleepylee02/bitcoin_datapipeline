"""Pytest configuration and shared fixtures."""

import pytest
import asyncio
import tempfile
import json
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock

from src.config.settings import IngestorSettings, BinanceConfig, AWSConfig, RetryConfig
from src.config.aws_config import AWSClientManager


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_config() -> IngestorSettings:
    """Create test configuration."""
    return IngestorSettings(
        service_name="test-ingestor",
        environment="test",
        mode="sbe",
        binance=BinanceConfig(
            symbols=["BTCUSDT"],
            rate_limit_requests_per_minute=60
        ),
        aws=AWSConfig(
            region="us-east-1",
            kinesis_trade_stream="test-market-sbe-trade",
            kinesis_bba_stream="test-market-sbe-bestbidask",
            kinesis_depth_stream="test-market-sbe-depth",
            s3_bucket="test-bitcoin-data-lake",
            localstack_endpoint="http://localhost:4566"
        ),
        retry=RetryConfig(max_attempts=2, initial_backoff_seconds=0.1)
    )


@pytest.fixture
def mock_aws_client_manager():
    """Mock AWS client manager."""
    manager = Mock(spec=AWSClientManager)
    
    # Mock clients
    manager.kinesis_client = Mock()
    manager.s3_client = Mock()
    manager.cloudwatch_client = Mock()
    
    # Mock verification methods
    manager.verify_connections = Mock(return_value={
        'kinesis': 'healthy',
        's3': 'healthy',
        'cloudwatch': 'healthy'
    })
    
    manager.ensure_streams_exist = AsyncMock(return_value=True)
    manager.ensure_bucket_exists = AsyncMock(return_value=True)
    
    return manager


@pytest.fixture
def sample_trade_data() -> Dict[str, Any]:
    """Sample trade data for testing."""
    return {
        'symbol': 'BTCUSDT',
        'event_ts': 1640995200000,
        'ingest_ts': 1640995200100,
        'trade_id': 12345,
        'price': 45000.50,
        'qty': 0.1,
        'is_buyer_maker': False,
        'source': 'sbe'
    }


@pytest.fixture
def sample_bba_data() -> Dict[str, Any]:
    """Sample best bid/ask data for testing."""
    return {
        'symbol': 'BTCUSDT',
        'event_ts': 1640995200000,
        'ingest_ts': 1640995200100,
        'bid_px': 44999.99,
        'bid_sz': 0.5,
        'ask_px': 45000.01,
        'ask_sz': 0.3,
        'source': 'sbe'
    }


@pytest.fixture
def sample_depth_data() -> Dict[str, Any]:
    """Sample depth data for testing."""
    return {
        'symbol': 'BTCUSDT',
        'event_ts': 1640995200000,
        'ingest_ts': 1640995200100,
        'bids': [['44999.99', '0.5'], ['44999.98', '1.0']],
        'asks': [['45000.01', '0.3'], ['45000.02', '0.8']],
        'source': 'sbe'
    }


@pytest.fixture
def sample_binance_trade_message() -> str:
    """Sample Binance WebSocket trade message."""
    return json.dumps({
        'e': 'trade',
        'E': 1640995200000,
        's': 'BTCUSDT',
        't': 12345,
        'p': '45000.50',
        'q': '0.1',
        'm': False
    })


@pytest.fixture
def sample_binance_bba_message() -> str:
    """Sample Binance WebSocket best bid/ask message."""
    return json.dumps({
        'e': 'bookTicker',
        'u': 400900217,
        's': 'BTCUSDT',
        'b': '44999.99',
        'B': '0.5',
        'a': '45000.01',
        'A': '0.3'
    })


@pytest.fixture
def temp_config_file(test_config: IngestorSettings):
    """Create a temporary configuration file."""
    config_dict = test_config.dict()
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        import yaml
        yaml.dump(config_dict, f)
        return f.name


@pytest.fixture
def mock_kinesis_response():
    """Mock Kinesis put_records response."""
    return {
        'FailedRecordCount': 0,
        'Records': [
            {
                'SequenceNumber': '12345',
                'ShardId': 'shardId-000000000000'
            }
        ]
    }


@pytest.fixture
def mock_s3_response():
    """Mock S3 put_object response."""
    return {
        'ETag': '"123456789"',
        'VersionId': 'v1'
    }


@pytest.fixture
def mock_websocket():
    """Mock WebSocket connection."""
    websocket = AsyncMock()
    websocket.closed = False
    websocket.close = AsyncMock()
    return websocket


class MockAWSResponse:
    """Mock AWS API response."""
    
    def __init__(self, data: Dict[str, Any], status_code: int = 200):
        self.data = data
        self.status_code = status_code
    
    def __getitem__(self, key):
        return self.data[key]
    
    def get(self, key, default=None):
        return self.data.get(key, default)


@pytest.fixture
def mock_aws_responses():
    """Factory for creating mock AWS responses."""
    def _create_response(data: Dict[str, Any], status_code: int = 200):
        return MockAWSResponse(data, status_code)
    return _create_response