#!/usr/bin/env python3
"""Test script for SBE decoder with debug output."""

import sys
import os
sys.path.append('src')

from sbe_decoder.sbe_decoder_cpp import SBEDecoder, TRADES_STREAM_EVENT, BEST_BID_ASK_STREAM_EVENT, DEPTH_DIFF_STREAM_EVENT

def test_decoder():
    """Test the SBE decoder with debug output."""
    decoder = SBEDecoder()
    
    print("SBE Decoder Test")
    print("=" * 50)
    print(f"TRADES_STREAM_EVENT: {TRADES_STREAM_EVENT}")
    print(f"BEST_BID_ASK_STREAM_EVENT: {BEST_BID_ASK_STREAM_EVENT}")
    print(f"DEPTH_DIFF_STREAM_EVENT: {DEPTH_DIFF_STREAM_EVENT}")
    print()
    
    # Create some mock SBE message data for testing
    # This simulates what we'd receive from the WebSocket
    
    # Template 10000 (trades) - Mock SBE header + payload
    mock_trade_data = bytearray()
    mock_trade_data.extend((42).to_bytes(2, 'little'))    # blockLength
    mock_trade_data.extend((10000).to_bytes(2, 'little')) # templateId  
    mock_trade_data.extend((1).to_bytes(2, 'little'))     # schemaId
    mock_trade_data.extend((0).to_bytes(2, 'little'))     # version
    # Add some mock payload data
    mock_trade_data.extend(b'BTCUSDT\x00' + b'\x00' * 34)  # Mock payload
    
    try:
        print("Testing trade message (template 10000):")
        result = decoder.decode_message(bytes(mock_trade_data))
        print(f"Decoded: {result}")
        print()
    except Exception as e:
        print(f"Error decoding trade: {e}")
        print()
    
    # Template 10001 (bestBidAsk) - Mock SBE header + payload  
    mock_ticker_data = bytearray()
    mock_ticker_data.extend((50).to_bytes(2, 'little'))    # blockLength
    mock_ticker_data.extend((10001).to_bytes(2, 'little')) # templateId
    mock_ticker_data.extend((1).to_bytes(2, 'little'))     # schemaId
    mock_ticker_data.extend((0).to_bytes(2, 'little'))     # version
    # Add some mock payload data
    mock_ticker_data.extend(b'BTCUSDT\x00' + b'\x00' * 50)  # Mock payload
    
    try:
        print("Testing bestBidAsk message (template 10001):")
        result = decoder.decode_message(bytes(mock_ticker_data))
        print(f"Decoded: {result}")
        print()
    except Exception as e:
        print(f"Error decoding bestBidAsk: {e}")
        print()
    
    # Template 10003 (depth) - Mock SBE header + payload
    mock_depth_data = bytearray()
    mock_depth_data.extend((26).to_bytes(2, 'little'))    # blockLength
    mock_depth_data.extend((10003).to_bytes(2, 'little')) # templateId
    mock_depth_data.extend((1).to_bytes(2, 'little'))     # schemaId
    mock_depth_data.extend((0).to_bytes(2, 'little'))     # version
    # Add some mock payload data
    mock_depth_data.extend(b'BTCUSDT\x00' + b'\x00' * 26)  # Mock payload
    
    try:
        print("Testing depth message (template 10003):")
        result = decoder.decode_message(bytes(mock_depth_data))
        print(f"Decoded: {result}")
        print()
    except Exception as e:
        print(f"Error decoding depth: {e}")
        print()

if __name__ == "__main__":
    test_decoder()