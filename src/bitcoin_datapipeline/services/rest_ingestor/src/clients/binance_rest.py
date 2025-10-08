"""Binance REST API client for historical data backfill."""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from datetime import datetime, timedelta
import time
import json
from dataclasses import dataclass

from ..config.settings import BinanceConfig, RetryConfig
from ..utils.retry import exponential_backoff

logger = logging.getLogger(__name__)


@dataclass
class BackfillCheckpoint:
    """Checkpoint for resumable backfill operations."""
    symbol: str
    last_timestamp: int
    last_trade_id: Optional[int] = None
    last_agg_trade_id: Optional[int] = None
    total_records: int = 0


class BinanceRESTClient:
    """Binance REST API client for historical data backfill."""
    
    def __init__(self, config: BinanceConfig, retry_config: RetryConfig):
        self.config = config
        self.retry_config = retry_config
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(config.rate_limit_requests_per_minute)
        
        # Endpoints
        self.endpoints = {
            'aggTrades': '/api/v3/aggTrades',
            'trades': '/api/v3/historicalTrades',
            'klines': '/api/v3/klines',
            'depth': '/api/v3/depth'
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.request_timeout_seconds),
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make rate-limited HTTP request with retry logic."""
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        url = f"{self.config.rest_base_url}{endpoint}"
        
        # Rate limiting
        await self.rate_limiter.acquire()
        
        async def _request():
            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limit exceeded, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Rate limit exceeded"
                    )
                
                response.raise_for_status()
                return await response.json()
        
        return await exponential_backoff(
            _request,
            max_attempts=self.retry_config.max_attempts,
            initial_delay=self.retry_config.initial_backoff_seconds,
            max_delay=self.retry_config.max_backoff_seconds,
            backoff_factor=self.retry_config.backoff_multiplier,
            jitter=self.retry_config.jitter
        )
    
    async def get_agg_trades(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        from_id: Optional[int] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get aggregated trades for a symbol."""
        params = {
            'symbol': symbol,
            'limit': min(limit, 1000)  # API limit is 1000
        }
        
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        if from_id:
            params['fromId'] = from_id
        
        logger.debug(f"Fetching aggTrades for {symbol}: {params}")
        
        try:
            data = await self._make_request(self.endpoints['aggTrades'], params)
            logger.info(f"Retrieved {len(data)} aggTrades for {symbol}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch aggTrades for {symbol}: {e}")
            raise
    
    async def get_trades(
        self,
        symbol: str,
        from_id: Optional[int] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get individual trades for a symbol."""
        params = {
            'symbol': symbol,
            'limit': min(limit, 1000)
        }
        
        if from_id:
            params['fromId'] = from_id
        
        logger.debug(f"Fetching trades for {symbol}: {params}")
        
        try:
            data = await self._make_request(self.endpoints['trades'], params)
            logger.info(f"Retrieved {len(data)} trades for {symbol}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch trades for {symbol}: {e}")
            raise
    
    async def get_klines(
        self,
        symbol: str,
        interval: str = '1m',
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000
    ) -> List[List[Any]]:
        """Get kline/candlestick data for a symbol."""
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': min(limit, 1000)
        }
        
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        logger.debug(f"Fetching klines for {symbol}: {params}")
        
        try:
            data = await self._make_request(self.endpoints['klines'], params)
            logger.info(f"Retrieved {len(data)} klines for {symbol}")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch klines for {symbol}: {e}")
            raise
    
    async def get_depth_snapshot(
        self,
        symbol: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get order book depth snapshot."""
        params = {
            'symbol': symbol,
            'limit': limit
        }
        
        logger.debug(f"Fetching depth snapshot for {symbol}")
        
        try:
            data = await self._make_request(self.endpoints['depth'], params)
            logger.info(f"Retrieved depth snapshot for {symbol} with {len(data.get('bids', []))} bids and {len(data.get('asks', []))} asks")
            return data
        except Exception as e:
            logger.error(f"Failed to fetch depth snapshot for {symbol}: {e}")
            raise
    
    async def backfill_agg_trades(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        checkpoint: Optional[BackfillCheckpoint] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Backfill aggregated trades with pagination and checkpointing."""
        
        current_start = checkpoint.last_timestamp if checkpoint else int(start_time.timestamp() * 1000)
        end_ts = int(end_time.timestamp() * 1000)
        
        logger.info(f"Starting aggTrades backfill for {symbol} from {current_start} to {end_ts}")
        
        while current_start < end_ts:
            # Calculate batch end time (24 hours max per request to avoid timeouts)
            batch_end = min(current_start + (24 * 60 * 60 * 1000), end_ts)
            
            try:
                trades = await self.get_agg_trades(
                    symbol=symbol,
                    start_time=current_start,
                    end_time=batch_end,
                    limit=1000
                )
                
                if not trades:
                    # No more trades in this time range
                    current_start = batch_end + 1
                    continue
                
                # Process each trade
                for trade in trades:
                    # Normalize trade data
                    normalized_trade = {
                        'symbol': trade['s'],
                        'event_ts': trade['T'],
                        'ingest_ts': int(time.time() * 1000),
                        'trade_id': trade['a'],  # aggTradeId
                        'price': float(trade['p']),
                        'qty': float(trade['q']),
                        'is_buyer_maker': trade['m'],
                        'source': 'rest'
                    }
                    
                    yield normalized_trade
                    current_start = max(current_start, trade['T'] + 1)
                
                # Update checkpoint
                if checkpoint:
                    checkpoint.last_timestamp = current_start
                    checkpoint.last_agg_trade_id = trades[-1]['a']
                    checkpoint.total_records += len(trades)
                
                logger.debug(f"Processed batch for {symbol}: {len(trades)} trades, next start: {current_start}")
                
                # Small delay to be respectful to the API
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in aggTrades backfill for {symbol} at {current_start}: {e}")
                raise
        
        logger.info(f"Completed aggTrades backfill for {symbol}")


class RateLimiter:
    """Token bucket rate limiter for API requests."""
    
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.tokens = requests_per_minute
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire a token for making a request."""
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # Add tokens based on elapsed time
            self.tokens = min(
                self.requests_per_minute,
                self.tokens + elapsed * (self.requests_per_minute / 60.0)
            )
            self.last_update = now
            
            if self.tokens >= 1:
                self.tokens -= 1
            else:
                # Wait until we have a token
                wait_time = (1 - self.tokens) / (self.requests_per_minute / 60.0)
                await asyncio.sleep(wait_time)
                self.tokens = 0