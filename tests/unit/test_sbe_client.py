#!/usr/bin/env python3
"""
Simple test script to verify SBE client functionality
Run this to test if Binance SBE WebSocket client works correctly

Note: SBE client requires:
1. C++ SBE decoder to be built
2. Binance API key for SBE streams
"""

import asyncio
import sys
import os
from dataclasses import dataclass

# Imports will use proper Python package structure

@dataclass
class TestConfig:
    sbe_ws_url: str = "wss://stream-sbe.binance.com:9443"
    api_key: str = "your_binance_api_key_here"  # Set this!
    api_secret: str = "your_binance_api_secret_here"  # Set this!
    symbols: list = None
    stream_types: list = None
    reconnect_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30
    
    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["BTCUSDT"]
        if self.stream_types is None:
            self.stream_types = ["trade", "bestBidAsk", "depth"]

async def test_sbe_client():
    """Test the Binance SBE client with real WebSocket connection"""
    
    try:
        from bitcoin_datapipeline.services.sbe_ingestor.src.clients.binance_sbe import BinanceSBEClient, SBEMessageType
        
        config = TestConfig()
        
        # Check if API key is set
        if config.api_key == "your_binance_api_key_here":
            print("⚠️  WARNING: You need to set a real Binance API key!")
            print("   Edit this script and set config.api_key to your actual API key")
            print("   SBE streams require authentication")
            return False
        
        print("🔧 Testing Binance SBE Client")
        print(f"📡 Endpoint: {config.sbe_ws_url}")
        print(f"🔑 API Key: {config.api_key[:8]}...")
        
        client = BinanceSBEClient(config)
        
        # Test 1: Check if SBE decoder is available
        print("\n1️⃣ Checking SBE decoder...")
        try:
            stats = client.get_stats()
            if stats.get('sbe_mode'):
                print("✅ C++ SBE decoder is available")
            else:
                print("❌ SBE decoder not available")
                return False
        except Exception as e:
            print(f"❌ SBE decoder check failed: {e}")
            return False
        
        # Test 2: Test connection
        print("\n2️⃣ Testing WebSocket connection...")
        try:
            connected = await client.connect()
            if connected:
                print("✅ Connected to Binance SBE WebSocket")
            else:
                print("❌ Failed to connect")
                return False
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
        
        # Test 3: Receive messages for a short time
        print("\n3️⃣ Testing message reception (10 seconds)...")
        message_count = 0
        message_types = set()
        
        try:
            async for message in client.start_streaming():
                message_count += 1
                message_types.add(message.message_type.value)
                
                print(f"   📨 {message.message_type.value}: {message.symbol} @ {message.event_time}")
                
                # Stop after 10 messages or 10 seconds
                if message_count >= 10:
                    break
                    
            print(f"✅ Received {message_count} messages")
            print(f"   Message types: {list(message_types)}")
            
        except Exception as e:
            print(f"❌ Message streaming failed: {e}")
            return False
        finally:
            await client.disconnect()
        
        # Test 4: Check statistics
        print("\n4️⃣ Checking client statistics...")
        try:
            stats = client.get_stats()
            print(f"✅ Stats: {stats['messages_received']} received, {stats['messages_processed']} processed")
            print(f"   Decode errors: {stats['decode_errors']}")
            print(f"   Connections: {stats['connection_count']}")
            
        except Exception as e:
            print(f"❌ Stats check failed: {e}")
            return False
        
        print("\n🎉 All SBE client tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        if "sbe_decoder_cpp" in str(e):
            print("\n📋 To fix this:")
            print("   1. cd services/sbe-ingestor")
            print("   2. chmod +x build_sbe_decoder.sh")
            print("   3. ./build_sbe_decoder.sh")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

async def test_sbe_decoder_only():
    """Test just the SBE decoder without network connection"""
    
    print("🔧 Testing SBE Decoder Only")
    
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), 'services/sbe-ingestor/src'))
        from sbe_decoder.sbe_decoder_cpp import SBEDecoder
        
        decoder = SBEDecoder()
        print("✅ C++ SBE decoder loaded successfully")
        
        # Test with dummy data
        dummy_data = b"dummy_sbe_message"
        is_valid = decoder.is_valid_message(dummy_data)
        print(f"✅ Decoder validation works (dummy result: {is_valid})")
        
        return True
        
    except ImportError as e:
        print(f"❌ SBE decoder import failed: {e}")
        print("\n📋 To build the SBE decoder:")
        print("   cd services/sbe-ingestor")
        print("   ./build_sbe_decoder.sh")
        return False
    except Exception as e:
        print(f"❌ Decoder test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Bitcoin Pipeline - SBE Client Test")
    print("=" * 50)
    
    # First test just the decoder
    print("Phase 1: SBE Decoder Test")
    decoder_ok = asyncio.run(test_sbe_decoder_only())
    
    if not decoder_ok:
        print("\n❌ SBE decoder not available - build it first!")
        sys.exit(1)
    
    print("\nPhase 2: Full SBE Client Test")
    success = asyncio.run(test_sbe_client())
    
    if success:
        print("\n✅ SBE client is working correctly!")
        sys.exit(0)
    else:
        print("\n❌ SBE client test failed!")
        sys.exit(1)