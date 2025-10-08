"""Configuration settings for REST ingestor service."""

import os
import yaml
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class BinanceConfig:
    """Binance API configuration."""
    rest_base_url: str
    symbols: List[str]
    rate_limit_requests_per_minute: int
    request_timeout_seconds: int


@dataclass
class AWSConfig:
    """AWS configuration."""
    region: str
    s3_bucket: str
    s3_bronze_prefix: str
    s3_checkpoint_prefix: str
    endpoint_url: Optional[str] = None  # For LocalStack


@dataclass
class SchedulerConfig:
    """Scheduler configuration."""
    enabled: bool
    collection_interval: str
    data_types: List[str]
    overlap_minutes: int


@dataclass
class CheckpointConfig:
    """Checkpoint configuration."""
    storage_type: str  # "s3" or "local"
    local_directory: str


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
class RestIngestorConfig:
    """Main configuration for REST ingestor service."""
    binance: BinanceConfig
    aws: AWSConfig
    scheduler: SchedulerConfig
    checkpoint: CheckpointConfig
    retry: RetryConfig
    logging: LoggingConfig
    health: HealthConfig


def load_config(config_file: str) -> RestIngestorConfig:
    """Load configuration from YAML file."""
    
    # Load YAML file
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # Environment variable substitution
    config_data = _substitute_env_vars(config_data)
    
    # Create configuration objects
    binance_config = BinanceConfig(**config_data['binance'])
    aws_config = AWSConfig(**config_data['aws'])
    scheduler_config = SchedulerConfig(**config_data['scheduler'])
    checkpoint_config = CheckpointConfig(**config_data['checkpoint'])
    retry_config = RetryConfig(**config_data['retry'])
    logging_config = LoggingConfig(**config_data['logging'])
    health_config = HealthConfig(**config_data['health'])
    
    return RestIngestorConfig(
        binance=binance_config,
        aws=aws_config,
        scheduler=scheduler_config,
        checkpoint=checkpoint_config,
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