"""Data transformer for cleaning and normalizing S3 data for PostgreSQL."""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from decimal import Decimal, InvalidOperation

from .config.settings import DataConnectorConfig


logger = logging.getLogger(__name__)


class DataTransformer:
    """Transforms raw S3 data for PostgreSQL storage."""
    
    def __init__(self, config: DataConnectorConfig):
        self.config = config
        self.stats = {
            "records_transformed": 0,
            "records_skipped": 0,
            "validation_errors": 0
        }
        
        logger.info("DataTransformer initialized")
    
    async def transform(
        self, 
        raw_records: List[Dict[str, Any]], 
        file_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Transform raw records for database storage."""
        
        data_type = file_info.get("data_type", "unknown")
        symbol = file_info.get("symbol", "UNKNOWN")
        
        logger.debug(f"Transforming {len(raw_records)} records of type {data_type}")
        
        transformed_records = []
        
        for record in raw_records:
            try:
                if data_type == "aggTrades":
                    transformed = await self._transform_agg_trade(record, symbol)
                elif data_type == "klines":
                    transformed = await self._transform_kline(record, symbol)
                elif data_type == "depth_snapshots":
                    transformed = await self._transform_depth_snapshot(record, symbol)
                else:
                    logger.warning(f"Unknown data type: {data_type}")
                    self.stats["records_skipped"] += 1
                    continue
                
                if transformed:
                    transformed_records.append(transformed)
                    self.stats["records_transformed"] += 1
                else:
                    self.stats["records_skipped"] += 1
                
            except Exception as e:
                logger.warning(f"Error transforming record: {e}")
                self.stats["validation_errors"] += 1
        
        logger.info(f"Transformed {len(transformed_records)} out of {len(raw_records)} records")
        return transformed_records
    
    async def _transform_agg_trade(self, record: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
        """Transform aggregated trade record."""
        
        try:
            # Validate required fields
            required_fields = ['symbol', 'event_ts', 'trade_id', 'price', 'qty', 'is_buyer_maker']
            for field in required_fields:
                if field not in record:
                    logger.warning(f"Missing required field {field} in aggTrade record")
                    return None
            
            # Convert and validate data types
            price = self._safe_decimal_convert(record['price'])
            qty = self._safe_decimal_convert(record['qty'])
            
            if price is None or qty is None:
                logger.warning(f"Invalid price or quantity in aggTrade: {record}")
                return None
            
            # Build normalized record
            transformed = {
                "symbol": record['symbol'],
                "timestamp": int(record['event_ts']),
                "price": price,
                "volume": qty,
                "trade_id": int(record['trade_id']),
                "is_buyer_maker": bool(record['is_buyer_maker']),
                "source": record.get('source', 'rest'),
                "data_type": "aggTrade",
                "created_at": datetime.now()
            }
            
            # Add optional fields
            if 'ingest_ts' in record:
                transformed["ingest_timestamp"] = int(record['ingest_ts'])
            
            return transformed
            
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error transforming aggTrade record: {e}")
            return None
    
    async def _transform_kline(self, record: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
        """Transform kline record."""
        
        try:
            # Validate kline structure
            required_fields = ['open_time', 'open_price', 'high_price', 'low_price', 
                             'close_price', 'volume', 'close_time', 'quote_volume', 'trade_count']
            
            for field in required_fields:
                if field not in record:
                    logger.warning(f"Missing required field {field} in kline record")
                    return None
            
            # Convert prices and volumes
            open_price = self._safe_decimal_convert(record['open_price'])
            high_price = self._safe_decimal_convert(record['high_price'])
            low_price = self._safe_decimal_convert(record['low_price'])
            close_price = self._safe_decimal_convert(record['close_price'])
            volume = self._safe_decimal_convert(record['volume'])
            quote_volume = self._safe_decimal_convert(record['quote_volume'])
            
            if any(val is None for val in [open_price, high_price, low_price, close_price, volume]):
                logger.warning(f"Invalid price/volume data in kline: {record}")
                return None
            
            # Calculate VWAP (Volume Weighted Average Price)
            vwap = quote_volume / volume if volume > 0 else close_price
            
            transformed = {
                "symbol": record['symbol'],
                "timestamp": int(record['open_time']),
                "price": close_price,  # Use close price as primary price
                "volume": volume,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "quote_volume": quote_volume,
                "vwap": vwap,
                "trade_count": int(record['trade_count']),
                "interval": record.get('interval', '1m'),
                "source": "rest",
                "data_type": "kline",
                "created_at": datetime.now()
            }
            
            return transformed
            
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as e:
            logger.warning(f"Error transforming kline record: {e}")
            return None
    
    async def _transform_depth_snapshot(self, record: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
        """Transform depth snapshot record."""
        
        try:
            # Validate depth snapshot structure
            required_fields = ['symbol', 'timestamp', 'bids', 'asks']
            
            for field in required_fields:
                if field not in record:
                    logger.warning(f"Missing required field {field} in depth snapshot")
                    return None
            
            bids = record.get('bids', [])
            asks = record.get('asks', [])
            
            if not bids or not asks:
                logger.warning("Empty bids or asks in depth snapshot")
                return None
            
            # Calculate best bid/ask
            best_bid_price = self._safe_decimal_convert(bids[0][0]) if bids else None
            best_bid_size = self._safe_decimal_convert(bids[0][1]) if bids else None
            best_ask_price = self._safe_decimal_convert(asks[0][0]) if asks else None
            best_ask_size = self._safe_decimal_convert(asks[0][1]) if asks else None
            
            if any(val is None for val in [best_bid_price, best_ask_price]):
                logger.warning(f"Invalid best bid/ask in depth snapshot: {record}")
                return None
            
            # Calculate spread and mid price
            spread = best_ask_price - best_bid_price
            mid_price = (best_bid_price + best_ask_price) / 2
            
            transformed = {
                "symbol": record['symbol'],
                "timestamp": int(record['timestamp']),
                "price": mid_price,  # Use mid price as primary price
                "volume": best_bid_size + best_ask_size,  # Combined size at best levels
                "best_bid_price": best_bid_price,
                "best_bid_size": best_bid_size,
                "best_ask_price": best_ask_price,
                "best_ask_size": best_ask_size,
                "spread": spread,
                "mid_price": mid_price,
                "last_update_id": record.get('last_update_id'),
                "source": record.get('source', 'rest'),
                "data_type": "depth",
                "created_at": datetime.now()
            }
            
            return transformed
            
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error transforming depth snapshot: {e}")
            return None
    
    def _safe_decimal_convert(self, value: Any) -> Optional[Decimal]:
        """Safely convert value to Decimal."""
        
        if value is None:
            return None
        
        try:
            if isinstance(value, str):
                # Handle empty strings
                if not value.strip():
                    return None
                return Decimal(value)
            elif isinstance(value, (int, float)):
                return Decimal(str(value))
            elif isinstance(value, Decimal):
                return value
            else:
                logger.warning(f"Cannot convert {type(value)} to Decimal: {value}")
                return None
                
        except (InvalidOperation, ValueError) as e:
            logger.warning(f"Error converting {value} to Decimal: {e}")
            return None
    
    def _validate_timestamp(self, timestamp: Any) -> Optional[int]:
        """Validate and normalize timestamp."""
        
        try:
            ts = int(timestamp)
            
            # Basic sanity check: timestamp should be reasonable
            # (between 2020 and 2030 in milliseconds)
            min_ts = 1577836800000  # 2020-01-01
            max_ts = 1893456000000  # 2030-01-01
            
            if min_ts <= ts <= max_ts:
                return ts
            else:
                logger.warning(f"Timestamp out of expected range: {ts}")
                return None
                
        except (ValueError, TypeError):
            logger.warning(f"Invalid timestamp format: {timestamp}")
            return None
    
    async def add_derived_features(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add derived features to records."""
        
        if not records:
            return records
        
        # Sort records by timestamp for feature calculation
        records.sort(key=lambda x: x['timestamp'])
        
        for i, record in enumerate(records):
            try:
                # Add price change features
                if i > 0:
                    prev_record = records[i-1]
                    if prev_record['symbol'] == record['symbol']:
                        price_change = record['price'] - prev_record['price']
                        price_change_pct = (price_change / prev_record['price']) * 100
                        
                        record['price_change'] = price_change
                        record['price_change_pct'] = price_change_pct
                
                # Add time-based features
                dt = datetime.fromtimestamp(record['timestamp'] / 1000)
                record['hour_of_day'] = dt.hour
                record['day_of_week'] = dt.weekday()
                
            except Exception as e:
                logger.warning(f"Error adding derived features: {e}")
        
        return records
    
    def get_stats(self) -> Dict[str, Any]:
        """Get transformation statistics."""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset transformation statistics."""
        self.stats = {
            "records_transformed": 0,
            "records_skipped": 0,
            "validation_errors": 0
        }