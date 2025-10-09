#!/usr/bin/env python3
"""
Simple test script to verify REST client functionality
Run this to test if Binance REST API client works correctly
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import pytest

@dataclass
class RestTestConfig:
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

@pytest.mark.unit
async def test_rest_client():
    """Test the Binance REST client with real API calls"""
    
    from bitcoin_datapipeline.services.rest_ingestor.src.clients.binance_rest import BinanceRESTClient
    
    config = RestTestConfig()
    retry_config = RetryConfig()
    
    print("🔧 Testing Binance REST Client")
    print(f"📡 Endpoint: {config.rest_base_url}")
    
    async with BinanceRESTClient(config, retry_config) as client:
            
        # Test 1: Get recent aggTrades
        print("\n1️⃣ Testing aggTrades endpoint...")
        trades = await client.get_agg_trades(
            symbol="BTCUSDT",
            limit=5  # Just get 5 recent trades
        )
        print(f"✅ Got {len(trades)} aggTrades")
        assert len(trades) > 0, "Should get at least 1 trade"
        
        if trades:
            latest_trade = trades[-1]
            print(f"   Latest trade: {latest_trade['p']} @ {latest_trade['T']}")
            print(f"   Trade structure: {list(latest_trade.keys())}")
            assert 'p' in latest_trade, "Trade should have price field"
            assert 'T' in latest_trade, "Trade should have timestamp field"
            
        # Test 2: Get klines data  
        print("\n2️⃣ Testing klines endpoint...")
        klines = await client.get_klines(
            symbol="BTCUSDT",
            interval="1m",
            limit=3
        )
        print(f"✅ Got {len(klines)} klines")
        assert len(klines) > 0, "Should get at least 1 kline"
        
        if klines:
            print(f"   Latest kline close: {klines[-1][4]}")
            assert len(klines[-1]) >= 6, "Kline should have at least 6 fields"
            
        # Test 3: Get order book snapshot
        print("\n3️⃣ Testing depth snapshot...")
        depth = await client.get_depth_snapshot(
            symbol="BTCUSDT",
            limit=5
        )
        print(f"✅ Got depth with {len(depth.get('bids', []))} bids, {len(depth.get('asks', []))} asks")
        assert 'bids' in depth, "Depth should have bids"
        assert 'asks' in depth, "Depth should have asks"
        assert len(depth['bids']) > 0, "Should have at least 1 bid"
        assert len(depth['asks']) > 0, "Should have at least 1 ask"
        
        if depth.get('bids'):
            print(f"   Best bid: {depth['bids'][0][0]}")
        if depth.get('asks'):
            print(f"   Best ask: {depth['asks'][0][0]}")
            
        # Test 4: Test backfill functionality (small range)
        print("\n4️⃣ Testing backfill (5 minutes of data)...")
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=5)
        
        print(f"   Backfill range: {start_time} to {end_time}")
        
        trade_count = 0
        async for trade in client.backfill_agg_trades("BTCUSDT", start_time, end_time):
            trade_count += 1
            if trade_count == 1:
                print(f"   First backfilled trade: {trade.get('price')} @ {trade.get('event_ts')}")
                assert 'symbol' in trade, "Backfilled trade should have symbol"
                assert 'price' in trade, "Backfilled trade should have price"
                assert 'event_ts' in trade, "Backfilled trade should have timestamp"
            if trade_count >= 10:  # Limit to 10 trades for testing
                break
                
        print(f"✅ Backfill working, got {trade_count} trades")
        assert trade_count > 0, "Should get at least 1 trade from backfill"
                
    print("\n🎉 All REST client tests passed!")

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