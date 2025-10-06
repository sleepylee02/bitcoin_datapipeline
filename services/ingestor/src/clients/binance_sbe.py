"""Binance SBE WebSocket client for real-time market data."""

import asyncio
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
import logging
import time
import struct
from typing import Dict, Any, Optional, Callable, AsyncIterator
from dataclasses import dataclass
from enum import Enum

from ..config.settings import BinanceConfig
from ..utils.retry import CircuitBreaker

# Import C++ SBE decoder for high-performance binary parsing
try:
    from ..sbe_decoder.sbe_decoder_cpp import (
        SBEDecoder, 
        TRADES_STREAM_EVENT, 
        BEST_BID_ASK_STREAM_EVENT, 
        DEPTH_DIFF_STREAM_EVENT,
        EXPECTED_SCHEMA_ID,
        EXPECTED_SCHEMA_VERSION
    )
    SBE_DECODER_AVAILABLE = True
except ImportError:
    SBE_DECODER_AVAILABLE = False
    raise ImportError("C++ SBE decoder is required for SBE client. Run './build_sbe_decoder.sh' to build it.")

logger = logging.getLogger(__name__)


class SBEMessageType(Enum):
    """SBE message types from Binance."""
    TRADE = "trade"
    BEST_BID_ASK = "bestBidAsk"
    DEPTH = "depth"
    PARTIAL_DEPTH = "depth@100ms"


@dataclass
class SBEMessage:
    """Parsed SBE message container."""
    message_type: SBEMessageType
    symbol: str
    event_time: int
    data: Dict[str, Any]
    raw_message: str


class BinanceSBEClient:
    """
    Binance SBE WebSocket client for real-time market data.
    
    Uses high-performance C++ decoder for parsing Binance SBE binary messages.
    Provides sub-millisecond parsing latency for real-time trading pipelines.
    """
    
    def __init__(self, config: BinanceConfig):
        self.config = config
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            expected_exception=WebSocketException
        )
        
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._message_handlers: Dict[SBEMessageType, Callable] = {}
        
        # Initialize C++ SBE decoder for high-performance binary parsing
        self.sbe_decoder = SBEDecoder()
        logger.info(f"Initialized C++ SBE decoder (schema {EXPECTED_SCHEMA_ID}:{EXPECTED_SCHEMA_VERSION})")
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'messages_processed': 0,
            'decode_errors': 0,
            'last_message_time': None,
            'connection_count': 0,
            'sbe_mode': True
        }
    
    def register_handler(self, message_type: SBEMessageType, handler: Callable):
        """Register a handler for specific message types."""
        self._message_handlers[message_type] = handler
        logger.info(f"Registered handler for {message_type.value}")
    
    async def connect(self) -> bool:
        """Establish WebSocket connection to Binance SBE endpoint."""
        try:
            # Build SBE WebSocket URL - direct stream format (not /stream?streams=...)
            streams = self._build_stream_list()
            ws_url = f"{self.config.sbe_ws_url}/{streams}"
            
            headers = {
                'User-Agent': 'BitcoinPipeline/1.0',
            }
            
            # Add API key for SBE streams (required for authenticated access)
            if self.config.api_key:
                headers['X-MBX-APIKEY'] = self.config.api_key
            else:
                logger.warning("No API key configured - SBE streams require authentication")
            
            logger.info(f"Connecting to Binance SBE: {ws_url}")
            
            # Connect with proper headers for SBE protocol
            self.websocket = await websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10,
                max_size=2**20,  # 1MB max message size
                compression=None,
                extra_headers=headers
            )
            
            self.stats['connection_count'] += 1
            self._reconnect_attempts = 0
            logger.info("Successfully connected to Binance SBE WebSocket")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Binance SBE: {e}")
            return False
    
    async def disconnect(self):
        """Close WebSocket connection."""
        self._running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            logger.info("Disconnected from Binance SBE WebSocket")
    
    async def start_streaming(self) -> AsyncIterator[SBEMessage]:
        """Start streaming messages from WebSocket."""
        self._running = True
        
        while self._running:
            try:
                if not self.websocket or self.websocket.closed:
                    if not await self._reconnect():
                        logger.error("Failed to establish connection, stopping stream")
                        break
                
                async for message in self._message_stream():
                    if message:
                        yield message
                        
            except Exception as e:
                logger.error(f"Error in message stream: {e}")
                await self._handle_connection_error()
    
    async def _message_stream(self) -> AsyncIterator[Optional[SBEMessage]]:
        """Internal message streaming loop."""
        try:
            async for raw_message in self.websocket:
                self.stats['messages_received'] += 1
                self.stats['last_message_time'] = time.time()
                
                try:
                    parsed_message = await self._parse_message(raw_message)
                    if parsed_message:
                        self.stats['messages_processed'] += 1
                        
                        # Call registered handlers
                        if parsed_message.message_type in self._message_handlers:
                            handler = self._message_handlers[parsed_message.message_type]
                            try:
                                await handler(parsed_message)
                            except Exception as e:
                                logger.error(f"Handler error for {parsed_message.message_type}: {e}")
                        
                        yield parsed_message
                        
                except Exception as e:
                    self.stats['decode_errors'] += 1
                    logger.warning(f"Failed to parse message: {e}")
                    logger.debug(f"Raw message: {raw_message[:200]}...")
                    continue
                    
        except ConnectionClosed:
            logger.warning("WebSocket connection closed by server")
        except Exception as e:
            logger.error(f"Unexpected error in message stream: {e}")
            raise
    
    async def _parse_message(self, raw_message) -> Optional[SBEMessage]:
        """
        Parse incoming SBE binary message using C++ decoder for maximum performance.
        """
        try:
            if isinstance(raw_message, bytes):
                # Handle binary SBE messages with C++ decoder
                return await self._decode_sbe_binary(raw_message)
            else:
                logger.warning(f"Received non-binary message on SBE connection: {type(raw_message)}")
                return None
                
        except Exception as e:
            logger.error(f"SBE message parsing failed: {e}")
            return None
    
    
    async def _decode_sbe_binary(self, raw_message: bytes) -> Optional[SBEMessage]:
        """
        Decode SBE binary message using high-performance C++ decoder.
        """
        try:
            if not self.sbe_decoder:
                logger.error("SBE decoder not available")
                return None
            
            # Debug: Check the actual schema version and message content
            header = None
            if len(raw_message) >= 8:  # Minimum size for SBE header
                import struct
                header = struct.unpack('<HHHH', raw_message[:8])  # little-endian: blockLength, templateId, schemaId, version
                logger.info(
                    f"🔍 SBE Header - blockLength: {header[0]}, templateId: {header[1]}, schemaId: {header[2]}, version: {header[3]}"
                )
                logger.info(f"🔍 Message size: {len(raw_message)} bytes")
                logger.info(f"🔍 Raw bytes (first 32): {raw_message[:32].hex()}")
            
            # Validate message format first
            if not self.sbe_decoder.is_valid_message(raw_message):
                logger.warning(
                    f"Invalid SBE message format or schema version. Expected schema {EXPECTED_SCHEMA_ID}:{EXPECTED_SCHEMA_VERSION}"
                )
                if header:
                    logger.warning(
                        f"Received: schemaId={header[2]}, version={header[3]}, templateId={header[1]}"
                    )
                else:
                    logger.warning("Received message too short to inspect header")
                return None
            
            try:
                decoded = self.sbe_decoder.decode_message(raw_message)
            except RuntimeError as e:
                logger.warning(f"Failed to decode SBE message: {e}")
                return None

            msg_type = decoded.get('msg_type')
            type_map = {
                'trade': SBEMessageType.TRADE,
                'bestBidAsk': SBEMessageType.BEST_BID_ASK,
                'bookTicker': SBEMessageType.BEST_BID_ASK,
                'depth': SBEMessageType.DEPTH,
                'depthDiff': SBEMessageType.DEPTH,
                'depth@100ms': SBEMessageType.PARTIAL_DEPTH,
            }

            message_type = type_map.get(msg_type)
            if not message_type and header:
                template_id = header[1]
                template_to_type = {
                    10000: SBEMessageType.TRADE,
                    10001: SBEMessageType.BEST_BID_ASK,
                    10002: SBEMessageType.DEPTH,
                    10003: SBEMessageType.DEPTH,
                }
                message_type = template_to_type.get(template_id)
                if not message_type:
                    logger.info(f"📋 Discovered new template ID: {template_id} - add to mapping if needed")
                    message_type = SBEMessageType.TRADE
            if not message_type:
                message_type = SBEMessageType.TRADE

            normalized_data = self._normalize_decoded_data(decoded, message_type)

            return SBEMessage(
                message_type=message_type,
                symbol=normalized_data.get('symbol', 'BTCUSDT'),
                event_time=normalized_data.get('event_ts', int(time.time() * 1000)),
                data=normalized_data,
                raw_message=f"SBE template={header[1] if header else 'unknown'} size={len(raw_message)}"
            )

        except Exception as e:
            logger.error(f"SBE binary decoding failed: {e}")
            return None

    def _normalize_decoded_data(self, decoded: Dict[str, Any], message_type: SBEMessageType) -> Dict[str, Any]:
        """Normalize decoder output to match internal expectations."""
        normalized = {**decoded}

        # Ensure consistent source and msg_type casing
        normalized['source'] = 'sbe'
        normalized['msg_type'] = message_type.value

        # Normalize symbol casing if present
        symbol = normalized.get('symbol')
        if isinstance(symbol, str):
            normalized['symbol'] = symbol.upper()

        # Force millisecond timestamps
        for ts_field in ('event_ts', 'ingest_ts'):
            if ts_field in normalized and normalized[ts_field] is not None:
                normalized[ts_field] = int(normalized[ts_field])

        if message_type == SBEMessageType.DEPTH:
            normalized['bids'] = self._convert_depth_levels(normalized.get('bids'))
            normalized['asks'] = self._convert_depth_levels(normalized.get('asks'))
        
        return normalized

    def _convert_depth_levels(self, levels: Optional[Any]) -> list:
        """Convert depth levels to [[price, qty], ...] string pairs."""
        if not levels:
            return []

        normalized_levels = []
        for level in levels:
            price = None
            qty = None

            if isinstance(level, dict):
                price = level.get('price')
                qty = level.get('qty')
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                price, qty = level[0], level[1]

            if price is None or qty is None:
                continue

            normalized_levels.append([
                self._format_numeric(price),
                self._format_numeric(qty)
            ])

        return normalized_levels

    def _format_numeric(self, value: Any) -> str:
        """Format numeric values as compact strings for Avro payloads."""
        if value is None:
            return "0"

        if isinstance(value, bool):
            return "1" if value else "0"

        if isinstance(value, (int, float)):
            return format(value, '.16g')

        return str(value)

    def _build_stream_list(self) -> str:
        """Build stream list for SBE WebSocket subscription."""
        streams = []
        
        for symbol in self.config.symbols:
            symbol_lower = symbol.lower()
            # Subscribe to SBE-specific stream names
            streams.extend([
                f"{symbol_lower}@trade",        # TradesStreamEvent
                f"{symbol_lower}@bestBidAsk",   # BestBidAskStreamEvent (correct for SBE)
                f"{symbol_lower}@depth"         # DepthDiffStreamEvent
            ])
        
        # For multi-stream subscription: /stream?streams=stream1/stream2/...
        return "/".join(streams) if streams else "btcusdt@trade"
    
    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            return False
        
        self._reconnect_attempts += 1
        delay = min(2 ** self._reconnect_attempts, 60)  # Max 60 seconds
        
        logger.info(f"Reconnection attempt {self._reconnect_attempts} in {delay}s")
        await asyncio.sleep(delay)
        
        return await self.connect()
    
    async def _handle_connection_error(self):
        """Handle connection errors and prepare for reconnection."""
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
            self.websocket = None
        
        logger.warning("Connection error occurred, will attempt reconnection")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection and processing statistics."""
        current_time = time.time()
        last_message_age = None
        
        if self.stats['last_message_time']:
            last_message_age = current_time - self.stats['last_message_time']
        
        return {
            **self.stats,
            'last_message_age_seconds': last_message_age,
            'is_connected': self.websocket is not None and not self.websocket.closed,
            'reconnect_attempts': self._reconnect_attempts
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the WebSocket connection."""
        stats = self.get_stats()
        
        health_status = {
            'healthy': True,
            'issues': []
        }
        
        # Check connection status
        if not stats['is_connected']:
            health_status['healthy'] = False
            health_status['issues'].append('WebSocket not connected')
        
        # Check message freshness (no messages for >30 seconds is concerning)
        if stats['last_message_age_seconds'] and stats['last_message_age_seconds'] > 30:
            health_status['healthy'] = False
            health_status['issues'].append(f"No messages for {stats['last_message_age_seconds']:.1f}s")
        
        # Check error rates
        if stats['messages_received'] > 0:
            error_rate = stats['decode_errors'] / stats['messages_received']
            if error_rate > 0.05:  # >5% error rate
                health_status['healthy'] = False
                health_status['issues'].append(f"High error rate: {error_rate:.2%}")
        
        return {
            'status': 'healthy' if health_status['healthy'] else 'unhealthy',
            'issues': health_status['issues'],
            'stats': stats
        }
