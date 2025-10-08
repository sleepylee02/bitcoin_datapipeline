"""Configuration settings for data connector service."""

import os
import yaml
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AWSConfig:
    """AWS configuration."""
    region: str
    s3_bucket: str
    s3_bronze_prefix: str
    endpoint_url: Optional[str] = None  # For LocalStack


@dataclass
class DatabaseConfig:
    """Database configuration."""
    host: str
    port: int
    user: str
    password: str
    name: str
    pool_min_size: int
    pool_max_size: int


@dataclass
class ETLConfig:
    """ETL configuration."""
    cycle_interval_seconds: int
    batch_size: int
    enable_derived_features: bool
    max_file_age_hours: int


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
class DataConnectorConfig:
    """Main configuration for data connector service."""
    aws: AWSConfig
    database: DatabaseConfig
    etl: ETLConfig
    logging: LoggingConfig
    health: HealthConfig


def load_config(config_file: str) -> DataConnectorConfig:
    """Load configuration from YAML file."""
    
    # Load YAML file
    with open(config_file, 'r') as f:
        config_data = yaml.safe_load(f)
    
    # Environment variable substitution
    config_data = _substitute_env_vars(config_data)
    
    # Create configuration objects
    aws_config = AWSConfig(**config_data['aws'])
    database_config = DatabaseConfig(**config_data['database'])
    etl_config = ETLConfig(**config_data['etl'])
    logging_config = LoggingConfig(**config_data['logging'])
    health_config = HealthConfig(**config_data['health'])
    
    return DataConnectorConfig(
        aws=aws_config,
        database=database_config,
        etl=etl_config,
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