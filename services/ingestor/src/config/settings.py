"""Configuration settings using Pydantic for validation."""

from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field, validator
from pydantic_settings import BaseSettings
import os
import re


class BinanceConfig(BaseModel):
    """Binance API configuration."""
    rest_base_url: str = Field(default="https://data-api.binance.vision", description="Binance REST API base URL")
    sbe_ws_url: str = Field(default="wss://stream-sbe.binance.com/ws", description="Binance SBE WebSocket URL")
    symbols: List[str] = Field(default=["BTCUSDT"], description="Trading symbols to ingest")
    rate_limit_requests_per_minute: int = Field(default=1200, description="API rate limit")
    request_timeout_seconds: int = Field(default=30, description="HTTP request timeout")
    
    # SBE authentication (required for SBE streams)
    api_key: Optional[str] = Field(default=None, description="Binance API key for SBE streams")
    api_secret: Optional[str] = Field(default=None, description="Binance API secret")
    sbe_schema_version: str = Field(default="1:0", description="SBE schema ID:version")


class AWSConfig(BaseModel):
    """AWS services configuration."""
    region: str = Field(default="us-east-1", description="AWS region")
    
    # AWS credentials (optional - use IAM roles in production)
    access_key_id: Optional[str] = Field(default=None, description="AWS access key ID")
    secret_access_key: Optional[str] = Field(default=None, description="AWS secret access key")
    
    # Kinesis Data Streams
    kinesis_trade_stream: str = Field(default="market-sbe-trade", description="Kinesis stream for trades")
    kinesis_bba_stream: str = Field(default="market-sbe-bestbidask", description="Kinesis stream for best bid/ask")
    kinesis_depth_stream: str = Field(default="market-sbe-depth", description="Kinesis stream for depth")
    kinesis_batch_size: int = Field(default=500, description="Kinesis batch size")
    kinesis_flush_interval_seconds: int = Field(default=1, description="Kinesis flush interval")
    
    # S3
    s3_bucket: str = Field(default="bitcoin-data-lake", description="S3 bucket for data lake")
    s3_bronze_prefix: str = Field(default="bronze", description="S3 prefix for bronze layer")
    
    # LocalStack overrides for local development
    localstack_endpoint: Optional[str] = Field(default=None, description="LocalStack endpoint URL")
    
    @validator('localstack_endpoint')
    def set_localstack_defaults(cls, v):
        if v and v.startswith('http://localhost'):
            return v
        return v


class RetryConfig(BaseModel):
    """Retry configuration for resilience."""
    max_attempts: int = Field(default=5, description="Maximum retry attempts")
    initial_backoff_seconds: float = Field(default=1.0, description="Initial backoff delay")
    max_backoff_seconds: float = Field(default=60.0, description="Maximum backoff delay")
    backoff_multiplier: float = Field(default=2.0, description="Backoff multiplier")
    jitter: bool = Field(default=True, description="Add jitter to backoff")


class HealthConfig(BaseModel):
    """Health check service configuration."""
    port: int = Field(default=8080, description="Health check server port")
    host: str = Field(default="0.0.0.0", description="Health check server host")
    endpoint: str = Field(default="/health", description="Health check endpoint path")


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="json", description="Log format: json or text")
    output: str = Field(default="stdout", description="Log output destination")


class MetricsConfig(BaseModel):
    """Metrics configuration."""
    enable_prometheus: bool = Field(default=True, description="Enable Prometheus metrics")
    prometheus_port: int = Field(default=8081, description="Prometheus metrics port")
    enable_cloudwatch: bool = Field(default=True, description="Enable CloudWatch metrics")
    metrics_namespace: str = Field(default="BitcoinPipeline/Ingestor", description="CloudWatch namespace")


class IngestorSettings(BaseSettings):
    """Main ingestor service settings."""
    
    # Service configuration
    service_name: str = Field(default="bitcoin-ingestor", description="Service name")
    environment: str = Field(default="local", description="Environment: local, dev, prod")
    mode: str = Field(default="sbe", description="Operation mode: rest, sbe, or both")
    
    # Component configurations
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    
    # Schema paths
    schema_base_path: str = Field(default="../../schemas/avro", description="Base path for Avro schemas")
    
    @validator('mode')
    def validate_mode(cls, v):
        if v not in ['rest', 'sbe', 'both']:
            raise ValueError("Mode must be 'rest', 'sbe', or 'both'")
        return v
    
    @validator('environment')
    def validate_environment(cls, v):
        if v not in ['local', 'dev', 'prod']:
            raise ValueError("Environment must be 'local', 'dev', or 'prod'")
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "__"
        case_sensitive = False


def substitute_env_vars(obj: Any) -> Any:
    """
    Recursively substitute environment variables in configuration objects.
    
    Supports syntax:
    - ${VAR_NAME} - Required variable (raises error if not found)
    - ${VAR_NAME:-default} - Optional variable with default value
    
    Args:
        obj: Configuration object (dict, list, string, or other)
        
    Returns:
        Object with environment variables substituted
        
    Raises:
        ValueError: If required environment variable is not found
    """
    if isinstance(obj, dict):
        return {key: substitute_env_vars(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [substitute_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        def replace_env_var(match):
            var_expr = match.group(1)
            
            # Handle default values: VAR_NAME:-default_value
            if ':-' in var_expr:
                var_name, default_value = var_expr.split(':-', 1)
                return os.getenv(var_name.strip(), default_value)
            else:
                var_name = var_expr.strip()
                value = os.getenv(var_name)
                if value is None:
                    raise ValueError(f"Required environment variable '{var_name}' is not set")
                return value
        
        # Replace ${VAR_NAME} and ${VAR_NAME:-default} patterns
        return re.sub(r'\$\{([^}]+)\}', replace_env_var, obj)
    else:
        return obj


def load_settings(config_file: Optional[str] = None) -> IngestorSettings:
    """
    Load settings from config file and environment variables.
    
    The config file supports environment variable substitution using ${VAR_NAME} syntax.
    Environment variables take precedence over config file values.
    
    Args:
        config_file: Path to YAML configuration file
        
    Returns:
        IngestorSettings: Validated configuration object
        
    Raises:
        ValueError: If required environment variables are missing
        FileNotFoundError: If config file doesn't exist
    """
    
    # Load from YAML config file if provided
    if config_file and os.path.exists(config_file):
        import yaml
        
        with open(config_file, 'r') as f:
            raw_config = yaml.safe_load(f)
        
        # Substitute environment variables in the loaded config
        config_data = substitute_env_vars(raw_config)
        
        # Create settings object (Pydantic will also load from environment variables)
        # Environment variables take precedence over config file values
        return IngestorSettings(**config_data)
    
    elif config_file:
        raise FileNotFoundError(f"Configuration file not found: {config_file}")
    
    # Load from environment variables only
    return IngestorSettings()