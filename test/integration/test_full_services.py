#!/usr/bin/env python3
"""
Test script for full ingestor services
Tests the complete REST and SBE ingestor services locally
"""

import asyncio
import sys
import os
import time
import signal
from dataclasses import dataclass
from typing import Optional

# Add services to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'services/rest-ingestor/src'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'services/sbe-ingestor/src'))

class ServiceTester:
    """Helper class to test services with timeout"""
    
    def __init__(self, test_duration: int = 30):
        self.test_duration = test_duration
        self.should_stop = False
        
    def stop_test(self):
        self.should_stop = True
        
    async def test_with_timeout(self, service_coro, service_name: str):
        """Test a service for specified duration"""
        print(f"🚀 Starting {service_name} test (will run for {self.test_duration}s)")
        
        try:
            # Start the service
            service_task = asyncio.create_task(service_coro)
            
            # Wait for test duration
            await asyncio.sleep(self.test_duration)
            
            # Stop the service
            service_task.cancel()
            try:
                await service_task
            except asyncio.CancelledError:
                pass
                
            print(f"✅ {service_name} test completed successfully")
            return True
            
        except Exception as e:
            print(f"❌ {service_name} test failed: {e}")
            return False

async def test_rest_ingestor():
    """Test the full REST ingestor service"""
    
    try:
        # Create a minimal test config
        test_config_content = """
binance:
  rest_base_url: "https://data-api.binance.vision"
  symbols: ["BTCUSDT"]
  rate_limit_requests_per_minute: 1200
  request_timeout_seconds: 30

aws:
  region: "us-east-1"
  s3_bucket: "test-bucket"
  s3_bronze_prefix: "bronze"
  s3_checkpoint_prefix: "checkpoints"
  use_local_storage: true
  local_storage_path: "./test-data"

scheduler:
  enabled: true
  collection_interval: "2m"
  data_types: ["aggTrades"]
  overlap_minutes: 1

checkpoint:
  storage_type: "local"
  local_directory: "./test-checkpoints"

retry:
  max_attempts: 3
  initial_backoff_seconds: 1.0
  max_backoff_seconds: 10.0
  backoff_multiplier: 2.0
  jitter: true

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers: ["console"]

health:
  enabled: true
  port: 8080
  host: "127.0.0.1"
"""
        
        # Write test config
        os.makedirs("./test-configs", exist_ok=True)
        with open("./test-configs/rest-test.yaml", "w") as f:
            f.write(test_config_content)
        
        print("1️⃣ Testing REST Ingestor Service...")
        
        # Import and test the service
        from main import RestIngestorService
        
        service = RestIngestorService("./test-configs/rest-test.yaml")
        
        # Test health check
        health = await service.health_check()
        print(f"   Health check: {health['status']}")
        
        # Start service for a short time
        tester = ServiceTester(test_duration=10)
        success = await tester.test_with_timeout(service.start(), "REST Ingestor")
        
        return success
        
    except Exception as e:
        print(f"❌ REST ingestor test failed: {e}")
        return False

async def test_sbe_ingestor():
    """Test the full SBE ingestor service"""
    
    try:
        # Create a minimal test config
        test_config_content = """
binance:
  sbe_base_url: "wss://stream-sbe.binance.com:9443"
  api_key: "${BINANCE_API_KEY:test_key}"
  api_secret: "${BINANCE_API_SECRET:test_secret}"
  symbols: ["BTCUSDT"]
  stream_types: ["trade", "bestBidAsk", "depth"]
  reconnect_interval_seconds: 5
  heartbeat_interval_seconds: 30

aws:
  region: "us-east-1"
  endpoint_url: "http://localhost:4566"

kinesis:
  streams:
    trade: "test-trade-stream"
    bestbidask: "test-bestbidask-stream"
    depth: "test-depth-stream"
  batch_size: 10
  flush_interval_seconds: 1
  max_retries: 3

retry:
  max_attempts: 3
  initial_backoff_seconds: 1.0
  max_backoff_seconds: 10.0
  backoff_multiplier: 2.0
  jitter: true

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers: ["console"]

health:
  enabled: true
  port: 8081
  host: "127.0.0.1"
"""
        
        # Write test config
        os.makedirs("./test-configs", exist_ok=True)
        with open("./test-configs/sbe-test.yaml", "w") as f:
            f.write(test_config_content)
        
        print("2️⃣ Testing SBE Ingestor Service...")
        
        # Import and test the service
        from main import SBEIngestorService
        
        service = SBEIngestorService("./test-configs/sbe-test.yaml")
        
        # Test health check
        health = await service.health_check()
        print(f"   Health check: {health['status']}")
        
        # Start service for a short time
        tester = ServiceTester(test_duration=10)
        success = await tester.test_with_timeout(service.start(), "SBE Ingestor")
        
        return success
        
    except Exception as e:
        print(f"❌ SBE ingestor test failed: {e}")
        return False

async def test_health_endpoints():
    """Test the health check endpoints"""
    
    print("3️⃣ Testing Health Endpoints...")
    
    try:
        import aiohttp
        
        # Test REST service health
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://127.0.0.1:8080/health', timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"   ✅ REST health: {data.get('status', 'unknown')}")
                    else:
                        print(f"   ⚠️  REST health returned {resp.status}")
        except:
            print("   ⚠️  REST health endpoint not accessible (service may not be running)")
        
        # Test SBE service health
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://127.0.0.1:8081/health', timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"   ✅ SBE health: {data.get('status', 'unknown')}")
                    else:
                        print(f"   ⚠️  SBE health returned {resp.status}")
        except:
            print("   ⚠️  SBE health endpoint not accessible (service may not be running)")
        
        return True
        
    except Exception as e:
        print(f"❌ Health endpoint test failed: {e}")
        return False

async def run_all_tests():
    """Run all service tests"""
    
    print("🧪 Bitcoin Pipeline - Full Service Tests")
    print("=" * 50)
    
    results = []
    
    # Test 1: REST Ingestor
    try:
        rest_success = await test_rest_ingestor()
        results.append(("REST Ingestor", rest_success))
    except Exception as e:
        print(f"❌ REST test crashed: {e}")
        results.append(("REST Ingestor", False))
    
    # Test 2: SBE Ingestor
    try:
        sbe_success = await test_sbe_ingestor()
        results.append(("SBE Ingestor", sbe_success))
    except Exception as e:
        print(f"❌ SBE test crashed: {e}")
        results.append(("SBE Ingestor", False))
    
    # Test 3: Health endpoints
    try:
        health_success = await test_health_endpoints()
        results.append(("Health Endpoints", health_success))
    except Exception as e:
        print(f"❌ Health test crashed: {e}")
        results.append(("Health Endpoints", False))
    
    # Summary
    print("\n📊 Test Results:")
    print("=" * 30)
    
    all_passed = True
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:20} {status}")
        if not success:
            all_passed = False
    
    print("\n" + ("🎉 All tests passed!" if all_passed else "❌ Some tests failed!"))
    return all_passed

if __name__ == "__main__":
    print("🚨 Note: This test will create test-configs/ and test-data/ directories")
    print("🚨 Make sure you have the required dependencies installed")
    print("🚨 For SBE tests, you need a valid Binance API key set in environment")
    print()
    
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)