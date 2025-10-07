"""Structured logging setup for the ingestor service."""

import logging
import logging.config
import json
import sys
from typing import Dict, Any
from datetime import datetime

from ..config.settings import LoggingConfig


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        
        # Create base log structure
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields from the record
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                          'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                          'thread', 'threadName', 'processName', 'process', 'getMessage']:
                log_data[key] = value
        
        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """Enhanced text formatter with colors for console output."""
    
    # Color codes for different log levels
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as colored text."""
        
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        level = record.levelname
        logger_name = record.name
        message = record.getMessage()
        
        # Add color if enabled
        if self.use_colors and level in self.COLORS:
            level = f"{self.COLORS[level]}{level}{self.COLORS['RESET']}"
        
        # Format: timestamp [LEVEL] logger: message
        formatted = f"{timestamp} [{level}] {logger_name}: {message}"
        
        # Add exception info if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        
        return formatted


def setup_logging(config: LoggingConfig, service_name: str = "ingestor") -> None:
    """
    Setup logging configuration for the service.
    
    Args:
        config: Logging configuration
        service_name: Name of the service for log context
    """
    
    # Determine formatter based on config
    if config.format.lower() == 'json':
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()
    
    # Setup handler based on output destination
    if config.output.lower() == 'stdout':
        handler = logging.StreamHandler(sys.stdout)
    elif config.output.lower() == 'stderr':
        handler = logging.StreamHandler(sys.stderr)
    else:
        # File output
        handler = logging.FileHandler(config.output)
    
    handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.upper()))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    
    # Add service context to all loggers
    class ServiceContextFilter(logging.Filter):
        def filter(self, record):
            record.service = service_name
            return True
    
    handler.addFilter(ServiceContextFilter())
    
    # Configure specific loggers to reduce noise
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.INFO)
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured: level={config.level}, format={config.format}, "
        f"output={config.output}, service={service_name}"
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(name)


def log_with_context(logger: logging.Logger, level: int, message: str, **context):
    """Log a message with additional context."""
    
    # Create a log record with extra context
    extra = {f"ctx_{key}": value for key, value in context.items()}
    logger.log(level, message, extra=extra)


def log_performance(logger: logging.Logger, operation: str, duration_ms: float, **context):
    """Log performance metrics."""
    
    log_with_context(
        logger,
        logging.INFO,
        f"Performance: {operation} completed in {duration_ms:.2f}ms",
        operation=operation,
        duration_ms=duration_ms,
        **context
    )


def log_error_with_context(logger: logging.Logger, error: Exception, operation: str, **context):
    """Log an error with full context and exception details."""
    
    log_with_context(
        logger,
        logging.ERROR,
        f"Error in {operation}: {str(error)}",
        operation=operation,
        error_type=type(error).__name__,
        error_message=str(error),
        **context
    )
    
    # Log the full traceback at debug level
    logger.debug(f"Full traceback for {operation}:", exc_info=error)


class LoggingContext:
    """Context manager for adding context to all log messages within a block."""
    
    def __init__(self, **context):
        self.context = context
        self.old_factory = None
    
    def __enter__(self):
        # Store the old record factory
        self.old_factory = logging.getLogRecordFactory()
        
        # Create new factory that adds our context
        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in self.context.items():
                setattr(record, f"ctx_{key}", value)
            return record
        
        logging.setLogRecordFactory(record_factory)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore the old record factory
        if self.old_factory:
            logging.setLogRecordFactory(self.old_factory)


# Convenience function for common logging patterns
def log_function_call(func):
    """Decorator to log function calls with timing."""
    
    import functools
    import time
    
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        start_time = time.time()
        
        try:
            if hasattr(args[0], '__class__'):
                # Method call
                func_name = f"{args[0].__class__.__name__}.{func.__name__}"
            else:
                # Function call
                func_name = func.__name__
            
            logger.debug(f"Calling {func_name}")
            result = await func(*args, **kwargs)
            
            duration_ms = (time.time() - start_time) * 1000
            log_performance(logger, func_name, duration_ms)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log_error_with_context(
                logger, e, func_name,
                duration_ms=duration_ms
            )
            raise
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        start_time = time.time()
        
        try:
            if hasattr(args[0], '__class__'):
                func_name = f"{args[0].__class__.__name__}.{func.__name__}"
            else:
                func_name = func.__name__
            
            logger.debug(f"Calling {func_name}")
            result = func(*args, **kwargs)
            
            duration_ms = (time.time() - start_time) * 1000
            log_performance(logger, func_name, duration_ms)
            
            return result
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log_error_with_context(
                logger, e, func_name,
                duration_ms=duration_ms
            )
            raise
    
    # Return appropriate wrapper based on function type
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper