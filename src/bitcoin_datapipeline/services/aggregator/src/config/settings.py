"""Configuration settings for aggregator service."""

import os
import yaml
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class AWSConfig:
    """AWS configuration."""
    region: str
    endpoint_url: Optional[str] = None  # For LocalStack


@dataclass
class KinesisConfig:
    """Kinesis configuration."""
    streams: Dict[str, str]  # stream_type -> stream_name mapping
    polling_interval_seconds: float
    max_records_per_request: int


@dataclass
class RedisConfig:
    """Redis configuration."""
    host: str
    port: int
    password: Optional[str]
    db: int
    key_prefix: str
    ttl_seconds: int
    socket_timeout: int
    socket_connect_timeout: int


@dataclass
class AggregationConfig:
    """Aggregation configuration."""
    min_messages: int
    max_interval_seconds: int
    check_interval_seconds: float


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
class AggregatorConfig:
    """Main configuration for aggregator service."""
    aws: AWSConfig
    kinesis: KinesisConfig
    redis: RedisConfig
    aggregation: AggregationConfig
    logging: LoggingConfig
    health: HealthConfig


def load_config(config_file: str) -> AggregatorConfig:
    """Load configuration from YAML file."""
    
    # Load YAML file
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # Environment variable substitution
    config_data = _substitute_env_vars(config_data)
    
    # Create configuration objects
    aws_config = AWSConfig(**config_data['aws'])
    kinesis_config = KinesisConfig(**config_data['kinesis'])
    redis_config = RedisConfig(**config_data['redis'])
    aggregation_config = AggregationConfig(**config_data['aggregation'])
    logging_config = LoggingConfig(**config_data['logging'])
    health_config = HealthConfig(**config_data['health'])
    
    return AggregatorConfig(
        aws=aws_config,
        kinesis=kinesis_config,
        redis=redis_config,
        aggregation=aggregation_config,
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