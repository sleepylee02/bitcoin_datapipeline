"""Feature builder for aggregating real-time market data into features."""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from collections import defaultdict
import statistics
import time

from .config.settings import AggregatorConfig


logger = logging.getLogger(__name__)


class FeatureBuilder:
    """Builds aggregated features from real-time market data messages."""
    
    def __init__(self, config: AggregatorConfig):
        self.config = config
        
        # Feature computation state
        self._price_history = defaultdict(list)
        self._volume_history = defaultdict(list)
        self._trade_history = defaultdict(list)
        
        # Statistics
        self.stats = {
            "features_built": 0,
            "messages_processed": 0,
            "computation_errors": 0
        }
        
        logger.info("FeatureBuilder initialized")
    
    async def build_features(
        self, 
        symbol: str, 
        messages: List[Dict[str, Any]], 
        message_type: str
    ) -> Optional[Dict[str, Any]]:
        """Build aggregated features from a batch of messages."""
        
        if not messages:
            return None
        
        try:
            logger.debug(f"Building features for {symbol} from {len(messages)} {message_type} messages")
            
            # Sort messages by timestamp
            sorted_messages = sorted(
                messages, 
                key=lambda x: x.get('data', {}).get('event_ts', x.get('timestamp', 0))
            )
            
            # Build features based on message type
            if message_type == "trade":
                features = await self._build_trade_features(symbol, sorted_messages)
            elif message_type == "bestBidAsk":
                features = await self._build_orderbook_features(symbol, sorted_messages)
            elif message_type == "depth":
                features = await self._build_depth_features(symbol, sorted_messages)
            else:
                logger.warning(f"Unknown message type for feature building: {message_type}")
                return None
            
            if features:
                # Add metadata
                features.update({
                    "symbol": symbol,
                    "timestamp": int(time.time()),
                    "message_count": len(messages),
                    "message_type": message_type,
                    "feature_version": "1.0"
                })
                
                self.stats["features_built"] += 1
                self.stats["messages_processed"] += len(messages)
                
                return features
            
        except Exception as e:
            logger.error(f"Error building features for {symbol}: {e}", exc_info=True)
            self.stats["computation_errors"] += 1
        
        return None
    
    async def _build_trade_features(
        self, 
        symbol: str, 
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build features from trade messages."""
        
        trades = [msg['data'] for msg in messages if 'data' in msg]
        
        if not trades:
            return {}
        
        # Extract trade data
        prices = []
        volumes = []
        buy_volumes = []
        sell_volumes = []
        timestamps = []
        
        for trade in trades:
            try:
                price = float(trade.get('price', 0))
                volume = float(trade.get('qty', trade.get('volume', 0)))
                is_buyer_maker = trade.get('is_buyer_maker', False)
                trade_ts = trade.get('event_ts', trade.get('timestamp', 0))
                
                if price > 0 and volume > 0:
                    prices.append(price)
                    volumes.append(volume)
                    timestamps.append(trade_ts)
                    
                    # Classify as buy/sell based on buyer maker flag
                    if is_buyer_maker:
                        sell_volumes.append(volume)  # Maker is selling
                    else:
                        buy_volumes.append(volume)   # Maker is buying
            
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid trade data: {trade}, error: {e}")
        
        if not prices:
            return {}
        
        # Calculate basic features
        latest_price = prices[-1]
        total_volume = sum(volumes)
        trade_count = len(prices)
        
        # Price features
        min_price = min(prices)
        max_price = max(prices)
        avg_price = statistics.mean(prices)
        
        # VWAP (Volume Weighted Average Price)
        total_value = sum(p * v for p, v in zip(prices, volumes))
        vwap = total_value / total_volume if total_volume > 0 else avg_price
        
        # Volume features
        total_buy_volume = sum(buy_volumes)
        total_sell_volume = sum(sell_volumes)
        
        # Trade velocity features
        time_span = (timestamps[-1] - timestamps[0]) / 1000 if len(timestamps) > 1 else 1
        trades_per_second = trade_count / max(time_span, 1)
        
        # Price movement features
        price_change = latest_price - prices[0] if len(prices) > 1 else 0
        price_change_pct = (price_change / prices[0] * 100) if prices[0] > 0 else 0
        
        # Volatility (standard deviation of prices)
        price_volatility = statistics.stdev(prices) if len(prices) > 1 else 0
        
        # Order flow imbalance
        volume_imbalance = (total_buy_volume - total_sell_volume) / max(total_volume, 1)
        
        # Average trade size
        avg_trade_size = total_volume / trade_count if trade_count > 0 else 0
        
        features = {
            "price": latest_price,
            "volume": total_volume,
            "vwap": vwap,
            "price_change": price_change,
            "price_change_pct": price_change_pct,
            "min_price": min_price,
            "max_price": max_price,
            "avg_price": avg_price,
            "price_volatility": price_volatility,
            "trade_count": trade_count,
            "trades_per_second": trades_per_second,
            "buy_volume": total_buy_volume,
            "sell_volume": total_sell_volume,
            "volume_imbalance": volume_imbalance,
            "avg_trade_size": avg_trade_size,
            "time_span_seconds": time_span
        }
        
        return features
    
    async def _build_orderbook_features(
        self, 
        symbol: str, 
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build features from best bid/ask messages."""
        
        orderbook_updates = [msg['data'] for msg in messages if 'data' in msg]
        
        if not orderbook_updates:
            return {}
        
        # Extract orderbook data
        bid_prices = []
        ask_prices = []
        bid_sizes = []
        ask_sizes = []
        spreads = []
        mid_prices = []
        
        for update in orderbook_updates:
            try:
                bid_price = float(update.get('bid_px', update.get('bid_price', 0)))
                ask_price = float(update.get('ask_px', update.get('ask_price', 0)))
                bid_size = float(update.get('bid_sz', update.get('bid_size', 0)))
                ask_size = float(update.get('ask_sz', update.get('ask_size', 0)))
                
                if bid_price > 0 and ask_price > 0:
                    bid_prices.append(bid_price)
                    ask_prices.append(ask_price)
                    bid_sizes.append(bid_size)
                    ask_sizes.append(ask_size)
                    
                    # Calculate spread and mid price
                    spread = ask_price - bid_price
                    mid_price = (bid_price + ask_price) / 2
                    
                    spreads.append(spread)
                    mid_prices.append(mid_price)
            
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid orderbook data: {update}, error: {e}")
        
        if not bid_prices:
            return {}
        
        # Latest values
        latest_bid = bid_prices[-1]
        latest_ask = ask_prices[-1]
        latest_spread = spreads[-1]
        latest_mid = mid_prices[-1]
        
        # Average values
        avg_bid = statistics.mean(bid_prices)
        avg_ask = statistics.mean(ask_prices)
        avg_spread = statistics.mean(spreads)
        avg_mid = statistics.mean(mid_prices)
        
        # Size features
        avg_bid_size = statistics.mean(bid_sizes)
        avg_ask_size = statistics.mean(ask_sizes)
        total_bid_size = sum(bid_sizes)
        total_ask_size = sum(ask_sizes)
        
        # Spread features
        min_spread = min(spreads)
        max_spread = max(spreads)
        spread_volatility = statistics.stdev(spreads) if len(spreads) > 1 else 0
        
        # Price movement from orderbook
        mid_change = mid_prices[-1] - mid_prices[0] if len(mid_prices) > 1 else 0
        mid_change_pct = (mid_change / mid_prices[0] * 100) if mid_prices[0] > 0 else 0
        
        features = {
            "price": latest_mid,  # Use mid price as primary price
            "bid_price": latest_bid,
            "ask_price": latest_ask,
            "spread": latest_spread,
            "spread_pct": (latest_spread / latest_mid * 100) if latest_mid > 0 else 0,
            "mid_price": latest_mid,
            "avg_bid": avg_bid,
            "avg_ask": avg_ask,
            "avg_spread": avg_spread,
            "avg_mid": avg_mid,
            "min_spread": min_spread,
            "max_spread": max_spread,
            "spread_volatility": spread_volatility,
            "bid_size": latest_bid_size if bid_sizes else 0,
            "ask_size": latest_ask_size if ask_sizes else 0,
            "avg_bid_size": avg_bid_size,
            "avg_ask_size": avg_ask_size,
            "total_bid_size": total_bid_size,
            "total_ask_size": total_ask_size,
            "size_imbalance": (total_bid_size - total_ask_size) / max(total_bid_size + total_ask_size, 1),
            "mid_change": mid_change,
            "mid_change_pct": mid_change_pct,
            "update_count": len(orderbook_updates)
        }
        
        return features
    
    async def _build_depth_features(
        self, 
        symbol: str, 
        messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build features from depth messages."""
        
        depth_updates = [msg['data'] for msg in messages if 'data' in msg]
        
        if not depth_updates:
            return {}
        
        # Use the latest depth snapshot for features
        latest_depth = depth_updates[-1]
        
        try:
            bids = latest_depth.get('bids', [])
            asks = latest_depth.get('asks', [])
            
            if not bids or not asks:
                return {}
            
            # Best levels
            best_bid_price = float(bids[0][0])
            best_bid_size = float(bids[0][1])
            best_ask_price = float(asks[0][0])
            best_ask_size = float(asks[0][1])
            
            # Calculate depth features
            spread = best_ask_price - best_bid_price
            mid_price = (best_bid_price + best_ask_price) / 2
            
            # Depth analysis (top 5 levels)
            bid_depth = sum(float(level[1]) for level in bids[:5])
            ask_depth = sum(float(level[1]) for level in asks[:5])
            
            # Weighted average prices (top 5 levels)
            bid_weighted_price = sum(
                float(level[0]) * float(level[1]) for level in bids[:5]
            ) / max(bid_depth, 1)
            
            ask_weighted_price = sum(
                float(level[0]) * float(level[1]) for level in asks[:5]
            ) / max(ask_depth, 1)
            
            features = {
                "price": mid_price,
                "bid_price": best_bid_price,
                "ask_price": best_ask_price,
                "spread": spread,
                "spread_pct": (spread / mid_price * 100) if mid_price > 0 else 0,
                "mid_price": mid_price,
                "bid_size": best_bid_size,
                "ask_size": best_ask_size,
                "bid_depth_5": bid_depth,
                "ask_depth_5": ask_depth,
                "depth_imbalance": (bid_depth - ask_depth) / max(bid_depth + ask_depth, 1),
                "bid_weighted_price": bid_weighted_price,
                "ask_weighted_price": ask_weighted_price,
                "total_levels": len(bids) + len(asks)
            }
            
            return features
        
        except (ValueError, KeyError, IndexError) as e:
            logger.warning(f"Error processing depth data: {e}")
            return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get feature builder statistics."""
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset feature builder statistics."""
        self.stats = {
            "features_built": 0,
            "messages_processed": 0,
            "computation_errors": 0
        }