"""Retry utilities with exponential backoff."""

import asyncio
import random
import logging
from typing import Callable, Any, TypeVar
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def exponential_backoff(
    func: Callable[[], T],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
) -> T:
    """
    Execute a function with exponential backoff retry logic.
    
    Args:
        func: Async function to execute
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        backoff_factor: Multiplier for delay after each failure
        jitter: Whether to add random jitter to delays
        exceptions: Tuple of exceptions to catch and retry on
    
    Returns:
        Result of the function call
        
    Raises:
        The last exception encountered if all retries fail
    """
    last_exception = None
    delay = initial_delay
    
    for attempt in range(max_attempts):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()
        except exceptions as e:
            last_exception = e
            
            if attempt == max_attempts - 1:
                # Last attempt failed, re-raise the exception
                logger.error(f"Function failed after {max_attempts} attempts: {e}")
                raise e
            
            # Calculate next delay
            if jitter:
                # Add jitter: ±25% of the delay
                jitter_range = delay * 0.25
                actual_delay = delay + random.uniform(-jitter_range, jitter_range)
            else:
                actual_delay = delay
            
            actual_delay = min(actual_delay, max_delay)
            
            logger.warning(
                f"Attempt {attempt + 1}/{max_attempts} failed: {e}. "
                f"Retrying in {actual_delay:.2f} seconds..."
            )
            
            await asyncio.sleep(actual_delay)
            delay *= backoff_factor
    
    # This should never be reached, but just in case
    if last_exception:
        raise last_exception


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for adding exponential backoff retry logic to async functions.
    
    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        backoff_factor: Multiplier for delay after each failure
        jitter: Whether to add random jitter to delays
        exceptions: Tuple of exceptions to catch and retry on
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def _func():
                return await func(*args, **kwargs)
            
            return await exponential_backoff(
                _func,
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                jitter=jitter,
                exceptions=exceptions
            )
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for fault tolerance.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit is open, requests fail immediately
    - HALF_OPEN: Testing if service has recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
        
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        
        if self.state == 'OPEN':
            if self._should_attempt_reset():
                self.state = 'HALF_OPEN'
                logger.info("Circuit breaker entering HALF_OPEN state")
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Success - reset failure count
            if self.state == 'HALF_OPEN':
                self.state = 'CLOSED'
                logger.info("Circuit breaker reset to CLOSED state")
            
            self.failure_count = 0
            return result
            
        except self.expected_exception as e:
            self._record_failure()
            raise e
    
    def _record_failure(self):
        """Record a failure and update circuit breaker state."""
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = 'OPEN'
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return False
        
        current_time = asyncio.get_event_loop().time()
        return current_time - self.last_failure_time >= self.recovery_timeout