#!/usr/bin/env python3
"""
Data Format Validation Test for Binance Clients

This script tests that the Binance clients produce data in the expected format
matching the Avro schemas defined in idea_specified_2.md.

Focus: Validate data structure, types, and field mapping.
"""

import asyncio
import logging
import sys
import time
import os
from pathlib import Path
from typing import Dict, Any, List

# Add src to path and parent for package imports
src_path = str(Path(__file__).parent.parent.parent / "src")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, src_path)

from src.config.settings import BinanceConfig, RetryConfig, load_settings
from src.clients.binance_rest import BinanceRESTClient
from src.clients.binance_sbe import BinanceSBEClient, SBEMessageType

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DataFormatValidator:
    """Validates that streaming data matches expected Avro schema formats."""
    
    def __init__(self):
        # Try to load settings from environment/config files
        try:
            logger.info("🔧 Loading configuration from environment...")
            
            # Load .env file manually since we're running from tests directory
            current_dir = Path.cwd()
            service_root = current_dir.parent.parent if current_dir.name == "ingestor_implement" else current_dir.parent
            env_file = service_root / ".env"
            
            if env_file.exists():
                logger.info(f"📁 Loading .env from: {env_file}")
                self._load_env_file(env_file)
            else:
                logger.warning(f"⚠️ .env file not found at {env_file}")
            
            # Check if we're in the tests directory and need to adjust path
            if "tests" in str(current_dir):
                config_file = service_root / "config" / "local.yaml"
                logger.info(f"📁 Looking for config at: {config_file}")
                
                if config_file.exists():
                    settings = load_settings(str(config_file))
                else:
                    logger.warning(f"⚠️ Config file not found at {config_file}")
                    settings = load_settings()
            else:
                settings = load_settings()
                
            self.config = settings.binance
            self.retry_config = settings.retry
            
            # Override symbols for testing
            self.config.symbols = ["BTCUSDT"]
            self.config.rate_limit_requests_per_minute = 60
            
            # Log config status
            api_status = "SET" if self.config.api_key else "NOT_SET"
            logger.info(f"📋 API Key: {api_status}")
            logger.info(f"📋 SBE URL: {self.config.sbe_ws_url}")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load settings: {e}")
            logger.info("📋 Using default config (no API credentials)")
            self.config = BinanceConfig(symbols=["BTCUSDT"], rate_limit_requests_per_minute=60)
            self.retry_config = RetryConfig(max_attempts=2)
        
        # Expected schemas from idea_specified_2.md
        self.expected_schemas = {
            'MarketTrade': {
                'symbol': str,
                'event_ts': int,
                'ingest_ts': int,
                'trade_id': int,
                'price': float,
                'qty': float,
                'is_buyer_maker': bool,
                'source': str
            },
            'BestBidAsk': {
                'symbol': str,
                'event_ts': int,
                'ingest_ts': int,
                'bid_px': float,
                'bid_sz': float,
                'ask_px': float,
                'ask_sz': float,
                'source': str
            },
            'DepthDelta': {
                'symbol': str,
                'event_ts': int,
                'ingest_ts': int,
                'bids': list,  # Array of arrays of strings
                'asks': list,  # Array of arrays of strings
                'source': str
            }
        }
    
    def _load_env_file(self, env_file_path: Path):
        """Load environment variables from .env file."""
        try:
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
                        
            # Log key status without showing values
            api_key_status = "SET" if os.getenv('BINANCE_API_KEY') else "NOT_SET"
            logger.info(f"📋 Loaded BINANCE_API_KEY: {api_key_status}")
        except Exception as e:
            logger.error(f"❌ Failed to load .env file: {e}")
    
    def validate_schema(self, data: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        """Validate data against expected schema."""
        expected_fields = self.expected_schemas[schema_name]
        validation_result = {
            'schema': schema_name,
            'valid': True,
            'missing_fields': [],
            'type_errors': [],
            'extra_fields': [],
            'sample_data': data
        }
        
        # Check for missing fields
        for field, expected_type in expected_fields.items():
            if field not in data:
                validation_result['missing_fields'].append(field)
                validation_result['valid'] = False
            else:
                # Check field types
                actual_value = data[field]
                if not self._check_type(actual_value, expected_type):
                    validation_result['type_errors'].append({
                        'field': field,
                        'expected': expected_type.__name__,
                        'actual': type(actual_value).__name__,
                        'value': actual_value
                    })
                    validation_result['valid'] = False
        
        # Check for extra fields
        for field in data:
            if field not in expected_fields:
                validation_result['extra_fields'].append(field)
        
        return validation_result
    
    def _check_type(self, value: Any, expected_type: type) -> bool:
        """Check if value matches expected type with special handling."""
        if expected_type == int:
            return isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected_type == list:
            if not isinstance(value, list):
                return False
            # For bids/asks, check if it's array of arrays
            if len(value) > 0:
                return isinstance(value[0], list) and len(value[0]) == 2
            return True
        else:
            return isinstance(value, expected_type)
    
    async def test_rest_data_format(self) -> List[Dict[str, Any]]:
        """Test REST client data format."""
        logger.info("🔍 Testing REST client data format...")
        
        results = []
        
        async with BinanceRESTClient(self.config, self.retry_config) as client:
            # Test aggTrades format
            logger.info("Testing aggTrades format...")
            trades = await client.get_agg_trades("BTCUSDT", limit=1)
            
            if trades:
                # First, let's see what the actual response looks like
                raw_trade = trades[0]
                logger.info(f"📋 Raw trade data keys: {list(raw_trade.keys())}")
                logger.info(f"📋 Raw trade sample: {raw_trade}")
                
                # Simulate the normalization that happens in backfill
                # Binance aggTrades API response format (different from WebSocket)
                normalized_trade = {
                    'symbol': 'BTCUSDT',  # We know the symbol from the request
                    'event_ts': raw_trade.get('T', raw_trade.get('timestamp', 0)),  # timestamp
                    'ingest_ts': int(time.time() * 1000),  # Current time in ms
                    'trade_id': raw_trade.get('a', raw_trade.get('id', 0)),  # aggregate trade id
                    'price': float(raw_trade.get('p', raw_trade.get('price', 0))),  # price
                    'qty': float(raw_trade.get('q', raw_trade.get('qty', 0))),  # quantity
                    'is_buyer_maker': raw_trade.get('m', raw_trade.get('isBuyerMaker', False)),  # was buyer the maker
                    'source': 'rest'
                }
                
                validation = self.validate_schema(normalized_trade, 'MarketTrade')
                validation['test_type'] = 'REST_aggTrades'
                results.append(validation)
                
                logger.info(f"✅ REST aggTrades: {'VALID' if validation['valid'] else 'INVALID'}")
                if not validation['valid']:
                    logger.error(f"   Issues: {validation}")
            
            # Test depth snapshot format
            logger.info("Testing depth snapshot format...")
            depth = await client.get_depth_snapshot("BTCUSDT", limit=5)
            
            if depth:
                # Simulate normalized depth data
                normalized_depth = {
                    'symbol': 'BTCUSDT',
                    'event_ts': 1640995200000,  # Mock time
                    'ingest_ts': 1640995200100,
                    'bids': depth['bids'][:5],  # Keep as string arrays
                    'asks': depth['asks'][:5],
                    'source': 'rest'
                }
                
                validation = self.validate_schema(normalized_depth, 'DepthDelta')
                validation['test_type'] = 'REST_depth'
                results.append(validation)
                
                logger.info(f"✅ REST depth: {'VALID' if validation['valid'] else 'INVALID'}")
                if not validation['valid']:
                    logger.error(f"   Issues: {validation}")
        
        return results
    
    async def test_sbe_data_format(self) -> List[Dict[str, Any]]:
        """Test SBE client data format."""
        logger.info("🔍 Testing SBE client data format...")
        
        results = []
        collected_samples = {
            'trade': None,
            'bba': None,
            'depth': None
        }
        
        try:
            # Note: SBE client requires C++ decoder and API key
            # For testing without API key, this will validate the data format structure
            client = BinanceSBEClient(self.config)
            
            # Register handlers to collect samples
            async def collect_trade(message):
                if collected_samples['trade'] is None:
                    collected_samples['trade'] = message.data
                    logger.info(f"📈 Collected trade sample: price={message.data.get('price')}")
                    logger.info(f"🔍 Trade debug: price_exp={message.data.get('price_exponent')}, qty_exp={message.data.get('qty_exponent')}")
                    logger.info(f"🔍 Trade debug: offset_fixed_end={message.data.get('debug_offset_fixed_end')}, data_size={message.data.get('debug_data_size')}")
                    logger.info(f"🔍 Trade debug: next_16_bytes={message.data.get('debug_next_16_bytes')}")
                    logger.info(f"🔍 Trade debug: marker_at_offset={message.data.get('debug_marker_at_offset')}, found_group={message.data.get('debug_found_group')}")
                    logger.info(f"🔍 Trade debug: group_block_length={message.data.get('debug_group_block_length')}, num_in_group={message.data.get('debug_num_in_group')}")
                    logger.info(f"🔍 Trade debug: price_mantissa={message.data.get('debug_price_mantissa')}, qty_mantissa={message.data.get('debug_qty_mantissa')}")
                    logger.info(f"🔍 Trade debug: trade_id={message.data.get('trade_id')}")
            
            async def collect_bba(message):
                if collected_samples['bba'] is None:
                    collected_samples['bba'] = message.data
                    logger.info(f"📊 Collected BBA sample: bid={message.data.get('bid_px')}, ask={message.data.get('ask_px')}")
            
            async def collect_depth(message):
                if collected_samples['depth'] is None:
                    collected_samples['depth'] = message.data
                    logger.info(f"📚 Collected depth sample: {len(message.data.get('bids', []))} bids, {len(message.data.get('asks', []))} asks")
            
            client.register_handler(SBEMessageType.TRADE, collect_trade)
            client.register_handler(SBEMessageType.BEST_BID_ASK, collect_bba)
            client.register_handler(SBEMessageType.DEPTH, collect_depth)
            
            # Connect and collect samples
            connected = await client.connect()
            if not connected:
                logger.error("❌ Failed to connect to SBE WebSocket")
                return results
            
            logger.info("🌐 Connected to SBE, collecting data samples...")
            
            # Collect for 10 seconds or until we have all samples
            start_time = asyncio.get_event_loop().time()
            async for message in client.start_streaming():
                # Check if we have all samples
                if all(sample is not None for sample in collected_samples.values()):
                    logger.info("✅ Collected all required samples")
                    break
                
                # Timeout after 10 seconds for faster debugging
                if asyncio.get_event_loop().time() - start_time > 10:
                    logger.warning("⏰ Timeout reached, validating collected samples")
                    break
            
            await client.disconnect()
            
            # Validate collected samples
            schema_mapping = {
                'trade': 'MarketTrade',
                'bba': 'BestBidAsk', 
                'depth': 'DepthDelta'
            }
            
            for sample_type, sample_data in collected_samples.items():
                if sample_data:
                    schema_name = schema_mapping[sample_type]
                    validation = self.validate_schema(sample_data, schema_name)
                    validation['test_type'] = f'SBE_{sample_type}'
                    results.append(validation)
                    
                    logger.info(f"✅ SBE {sample_type}: {'VALID' if validation['valid'] else 'INVALID'}")
                    if not validation['valid']:
                        logger.error(f"   Issues: {validation}")
                else:
                    logger.warning(f"⚠️ No {sample_type} sample collected")
                    results.append({
                        'test_type': f'SBE_{sample_type}',
                        'valid': False,
                        'error': 'No sample collected'
                    })
        
        except Exception as e:
            logger.error(f"❌ SBE test failed: {e}")
            results.append({
                'test_type': 'SBE_connection',
                'valid': False,
                'error': str(e)
            })
        
        return results
    
    def print_validation_report(self, results: List[Dict[str, Any]]):
        """Print detailed validation report."""
        logger.info("\n" + "="*80)
        logger.info("📋 DATA FORMAT VALIDATION REPORT")
        logger.info("="*80)
        
        valid_count = sum(1 for r in results if r.get('valid', False))
        total_count = len(results)
        
        logger.info(f"Overall: {valid_count}/{total_count} tests passed")
        logger.info("")
        
        for result in results:
            test_type = result.get('test_type', 'Unknown')
            valid = result.get('valid', False)
            status = "✅ VALID" if valid else "❌ INVALID"
            
            logger.info(f"{test_type}: {status}")
            
            if not valid:
                if 'missing_fields' in result and result['missing_fields']:
                    logger.error(f"   Missing fields: {result['missing_fields']}")
                
                if 'type_errors' in result and result['type_errors']:
                    logger.error("   Type errors:")
                    for error in result['type_errors']:
                        logger.error(f"     {error['field']}: expected {error['expected']}, got {error['actual']} ({error['value']})")
                
                if 'extra_fields' in result and result['extra_fields']:
                    logger.warning(f"   Extra fields: {result['extra_fields']}")
                
                if 'error' in result:
                    logger.error(f"   Error: {result['error']}")
            
            # Show sample data structure for valid results
            elif 'sample_data' in result:
                sample = result['sample_data']
                logger.info(f"   Sample: symbol={sample.get('symbol')}, source={sample.get('source')}")
                if 'price' in sample:
                    logger.info(f"           price={sample['price']}, qty={sample.get('qty')}")
                elif 'bid_px' in sample:
                    logger.info(f"           bid={sample['bid_px']}, ask={sample['ask_px']}")
                elif 'bids' in sample:
                    logger.info(f"           bids={len(sample['bids'])}, asks={len(sample['asks'])}")
        
        logger.info("\n" + "="*80)
        
        if valid_count == total_count:
            logger.info("🎉 ALL DATA FORMATS ARE VALID!")
            logger.info("   Your data streams match the expected Avro schemas perfectly.")
        else:
            logger.error(f"❌ {total_count - valid_count} FORMAT ISSUES FOUND")
            logger.error("   Please review the validation errors above.")
    
    async def run_validation(self):
        """Run complete data format validation."""
        logger.info("🚀 Starting data format validation...")
        
        all_results = []
        
        # Test REST formats
        rest_results = await self.test_rest_data_format()
        all_results.extend(rest_results)
        
        # Test SBE formats
        sbe_results = await self.test_sbe_data_format()
        all_results.extend(sbe_results)
        
        # Print comprehensive report
        self.print_validation_report(all_results)
        
        # Return success status
        return all(r.get('valid', False) for r in all_results)


async def main():
    """Main validation runner."""
    validator = DataFormatValidator()
    
    try:
        success = await validator.run_validation()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Validation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())