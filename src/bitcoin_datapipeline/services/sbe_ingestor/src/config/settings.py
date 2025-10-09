"""Configuration settings for SBE ingestor service."""

import os
import yaml
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class BinanceConfig:
    """Binance SBE configuration."""
    sbe_base_url: str
    api_key: str
    api_secret: str
    symbols: List[str]
    stream_types: List[str]
    reconnect_interval_seconds: int
    heartbeat_interval_seconds: int


@dataclass
class AWSConfig:
    """AWS configuration."""
    region: str
    endpoint_url: Optional[str] = None  # For LocalStack


@dataclass
class KinesisConfig:
    """Kinesis configuration."""
    streams: Dict[str, str]  # stream_type -> stream_name mapping
    batch_size: int
    flush_interval_seconds: int
    max_retries: int


@dataclass
class RetryConfig:
    """Retry configuration."""
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float
    backoff_multiplier: float
    jitter: bool


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str
    format: str
    handlers: List[str]


@dataclass
class HealthConfig:
    """Health check configuration."""
    enabled: bool
    port: int
    host: str


@dataclass
class SBEIngestorConfig:
    """Main configuration for SBE ingestor service."""
    binance: BinanceConfig
    aws: AWSConfig
    kinesis: KinesisConfig
    retry: RetryConfig
    logging: LoggingConfig
    health: HealthConfig


def load_config(config_file: str) -> SBEIngestorConfig:
    """Load configuration from YAML file."""
    
    # Load YAML file
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # Environment variable substitution
    config_data = _substitute_env_vars(config_data)
    
    # Create configuration objects
    binance_config = BinanceConfig(**config_data['binance'])
    aws_config = AWSConfig(**config_data['aws'])
    kinesis_config = KinesisConfig(**config_data['kinesis'])
    retry_config = RetryConfig(**config_data['retry'])
    logging_config = LoggingConfig(**config_data['logging'])
    health_config = HealthConfig(**config_data['health'])
    
    return SBEIngestorConfig(
        binance=binance_config,
        aws=aws_config,
        kinesis=kinesis_config,
        retry=retry_config,
        logging=logging_config,
        health=health_config
    )


def _substitute_env_vars(data):
    """Recursively substitute environment variables in configuration."""
    if isinstance(data, dict):
        return {key: _substitute_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str) and data.startswith('${') and data.endswith('}'):
        # Extract environment variable name and default value
        env_spec = data[2:-1]  # Remove ${ and }
        
        if ':' in env_spec:
            env_name, default_value = env_spec.split(':', 1)
        else:
            env_name, default_value = env_spec, None
        
        return os.getenv(env_name, default_value)
    else:
        return data