#!/usr/bin/env python3
"""
Simple test script to verify REST client functionality
Run this to test if Binance REST API client works correctly
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from dataclasses import dataclass

# Add services to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'services/rest-ingestor/src'))

@dataclass
class TestConfig:
    rest_base_url: str = "https://data-api.binance.vision"
    rate_limit_requests_per_minute: int = 1200
    request_timeout_seconds: int = 30

@dataclass 
class RetryConfig:
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 10.0
    backoff_multiplier: float = 2.0
    jitter: bool = True

async def test_rest_client():
    """Test the Binance REST client with real API calls"""
    
    try:
        from clients.binance_rest import BinanceRESTClient
        
        config = TestConfig()
        retry_config = RetryConfig()
        
        print("🔧 Testing Binance REST Client")
        print(f"📡 Endpoint: {config.rest_base_url}")
        
        async with BinanceRESTClient(config, retry_config) as client:
            
            # Test 1: Get recent aggTrades
            print("\n1️⃣ Testing aggTrades endpoint...")
            try:
                trades = await client.get_agg_trades(
                    symbol="BTCUSDT",
                    limit=5  # Just get 5 recent trades
                )
                print(f"✅ Got {len(trades)} aggTrades")
                if trades:
                    latest_trade = trades[-1]
                    print(f"   Latest trade: {latest_trade['p']} @ {latest_trade['T']}")
                    
            except Exception as e:
                print(f"❌ aggTrades failed: {e}")
                return False
            
            # Test 2: Get klines data  
            print("\n2️⃣ Testing klines endpoint...")
            try:
                klines = await client.get_klines(
                    symbol="BTCUSDT",
                    interval="1m",
                    limit=3
                )
                print(f"✅ Got {len(klines)} klines")
                if klines:
                    print(f"   Latest kline close: {klines[-1][4]}")
                    
            except Exception as e:
                print(f"❌ klines failed: {e}")
                return False
            
            # Test 3: Get order book snapshot
            print("\n3️⃣ Testing depth snapshot...")
            try:
                depth = await client.get_depth_snapshot(
                    symbol="BTCUSDT",
                    limit=5
                )
                print(f"✅ Got depth with {len(depth.get('bids', []))} bids, {len(depth.get('asks', []))} asks")
                if depth.get('bids'):
                    print(f"   Best bid: {depth['bids'][0][0]}")
                if depth.get('asks'):
                    print(f"   Best ask: {depth['asks'][0][0]}")
                    
            except Exception as e:
                print(f"❌ depth failed: {e}")
                return False
            
            # Test 4: Test backfill functionality (small range)
            print("\n4️⃣ Testing backfill (5 minutes of data)...")
            try:
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(minutes=5)
                
                trade_count = 0
                async for trade in client.backfill_agg_trades("BTCUSDT", start_time, end_time):
                    trade_count += 1
                    if trade_count >= 10:  # Limit to 10 trades for testing
                        break
                        
                print(f"✅ Backfill working, got {trade_count} trades")
                
            except Exception as e:
                print(f"❌ backfill failed: {e}")
                return False
                
        print("\n🎉 All REST client tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're in the project root directory")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Bitcoin Pipeline - REST Client Test")
    print("=" * 50)
    
    success = asyncio.run(test_rest_client())
    
    if success:
        print("\n✅ REST client is working correctly!")
        sys.exit(0)
    else:
        print("\n❌ REST client test failed!")
        sys.exit(1)