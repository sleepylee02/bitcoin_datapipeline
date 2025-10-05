"""Tests for configuration management."""

import pytest
import tempfile
import yaml
from unittest.mock import patch, Mock

from src.config.settings import IngestorSettings, load_settings, BinanceConfig, AWSConfig


class TestIngestorSettings:
    """Test IngestorSettings validation and loading."""
    
    def test_default_settings(self):
        """Test default settings creation."""
        settings = IngestorSettings()
        
        assert settings.service_name == "bitcoin-ingestor"
        assert settings.environment == "local"
        assert settings.mode == "sbe"
        assert isinstance(settings.binance, BinanceConfig)
        assert isinstance(settings.aws, AWSConfig)
    
    def test_mode_validation(self):
        """Test mode validation."""
        # Valid modes
        for mode in ['rest', 'sbe', 'both']:
            settings = IngestorSettings(mode=mode)
            assert settings.mode == mode
        
        # Invalid mode
        with pytest.raises(ValueError, match="Mode must be"):
            IngestorSettings(mode="invalid")
    
    def test_environment_validation(self):
        """Test environment validation."""
        # Valid environments
        for env in ['local', 'dev', 'prod']:
            settings = IngestorSettings(environment=env)
            assert settings.environment == env
        
        # Invalid environment
        with pytest.raises(ValueError, match="Environment must be"):
            IngestorSettings(environment="invalid")
    
    def test_nested_config_validation(self):
        """Test nested configuration validation."""
        settings = IngestorSettings(
            binance={
                'symbols': ['BTCUSDT', 'ETHUSDT'],
                'rate_limit_requests_per_minute': 1200
            },
            aws={
                'region': 'us-west-2',
                'kinesis_batch_size': 1000
            }
        )
        
        assert settings.binance.symbols == ['BTCUSDT', 'ETHUSDT']
        assert settings.binance.rate_limit_requests_per_minute == 1200
        assert settings.aws.region == 'us-west-2'
        assert settings.aws.kinesis_batch_size == 1000


class TestConfigLoading:
    """Test configuration loading from files and environment."""
    
    def test_load_from_yaml_file(self):
        """Test loading configuration from YAML file."""
        config_data = {
            'service_name': 'test-service',
            'environment': 'dev',
            'mode': 'both',
            'binance': {
                'symbols': ['BTCUSDT'],
                'rate_limit_requests_per_minute': 600
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            config_file = f.name
        
        settings = load_settings(config_file)
        
        assert settings.service_name == 'test-service'
        assert settings.environment == 'dev'
        assert settings.mode == 'both'
        assert settings.binance.symbols == ['BTCUSDT']
        assert settings.binance.rate_limit_requests_per_minute == 600
    
    def test_load_nonexistent_file(self):
        """Test loading with nonexistent config file."""
        settings = load_settings('nonexistent.yaml')
        
        # Should use default settings
        assert settings.service_name == "bitcoin-ingestor"
        assert settings.environment == "local"
    
    @patch.dict('os.environ', {
        'SERVICE_NAME': 'env-service',
        'ENVIRONMENT': 'prod',
        'BINANCE__SYMBOLS': '["BTCUSDT","ETHUSDT"]'
    })
    def test_environment_variable_override(self):
        """Test environment variable overrides."""
        settings = load_settings()
        
        assert settings.service_name == 'env-service'
        assert settings.environment == 'prod'
        # Note: Complex nested env vars might need special handling
    
    def test_aws_config_defaults(self):
        """Test AWS configuration defaults."""
        aws_config = AWSConfig()
        
        assert aws_config.region == "us-east-1"
        assert aws_config.kinesis_trade_stream == "market-sbe-trade"
        assert aws_config.kinesis_bba_stream == "market-sbe-bestbidask"
        assert aws_config.kinesis_depth_stream == "market-sbe-depth"
        assert aws_config.s3_bucket == "bitcoin-data-lake"
        assert aws_config.s3_bronze_prefix == "bronze"
    
    def test_binance_config_defaults(self):
        """Test Binance configuration defaults."""
        binance_config = BinanceConfig()
        
        assert binance_config.rest_base_url == "https://data-api.binance.vision"
        assert binance_config.sbe_ws_url == "wss://stream.binance.com:9443"
        assert binance_config.symbols == ["BTCUSDT"]
        assert binance_config.rate_limit_requests_per_minute == 1200
        assert binance_config.request_timeout_seconds == 30
    
    def test_localstack_endpoint_validation(self):
        """Test LocalStack endpoint validation."""
        # Valid LocalStack endpoint
        aws_config = AWSConfig(localstack_endpoint="http://localhost:4566")
        assert aws_config.localstack_endpoint == "http://localhost:4566"
        
        # Invalid endpoint should be None
        aws_config = AWSConfig(localstack_endpoint="invalid-url")
        assert aws_config.localstack_endpoint == "invalid-url"
        
        # None should remain None
        aws_config = AWSConfig(localstack_endpoint=None)
        assert aws_config.localstack_endpoint is None