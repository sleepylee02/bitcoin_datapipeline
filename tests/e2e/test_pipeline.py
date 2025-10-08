#!/usr/bin/env python3
"""
End-to-end test for the complete Bitcoin Pipeline
Tests the full data flow from ingestion to aggregation

This test requires:
- Docker environment running (docker-compose.test.yml)
- LocalStack with resources created
- All services healthy
"""

import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)

import asyncio
import aiohttp
import time
import json
from typing import Dict, Any

class PipelineE2ETester:
    """End-to-end tester for Bitcoin Pipeline"""
    
    def __init__(self):
        self.services = {
            'rest-ingestor': 'http://localhost:8080',
            'sbe-ingestor': 'http://localhost:8081',
            'aggregator': 'http://localhost:8082'
        }
        self.localstack_endpoint = 'http://localhost:4566'
        self.redis_endpoint = 'redis://localhost:6379'
        
    async def test_service_health(self) -> Dict[str, bool]:
        """Test all service health endpoints"""
        
        print("🔍 Testing service health...")
        results = {}
        
        async with aiohttp.ClientSession() as session:
            for service_name, base_url in self.services.items():
                try:
                    health_url = f"{base_url}/health"
                    async with session.get(health_url, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            status = data.get('status', 'unknown')
                            results[service_name] = status == 'healthy'
                            print(f"   ✅ {service_name}: {status}")
                        else:
                            results[service_name] = False
                            print(f"   ❌ {service_name}: HTTP {resp.status}")
                except Exception as e:
                    results[service_name] = False
                    print(f"   ❌ {service_name}: {e}")
        
        return results
    
    async def test_kinesis_streams(self) -> bool:
        """Test Kinesis streams are available and accessible"""
        
        print("🌊 Testing Kinesis streams...")
        
        try:
            import boto3
            
            kinesis = boto3.client(
                'kinesis',
                endpoint_url=self.localstack_endpoint,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test'
            )
            
            # List streams
            response = kinesis.list_streams()
            streams = response.get('StreamNames', [])
            
            expected_streams = [
                'market-trade-stream',
                'market-bestbidask-stream', 
                'market-depth-stream'
            ]
            
            for stream in expected_streams:
                if stream in streams:
                    print(f"   ✅ {stream} exists")
                else:
                    print(f"   ❌ {stream} missing")
                    return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Kinesis test failed: {e}")
            return False
    
    async def test_s3_bucket(self) -> bool:
        """Test S3 bucket is available"""
        
        print("🪣 Testing S3 bucket...")
        
        try:
            import boto3
            
            s3 = boto3.client(
                's3',
                endpoint_url=self.localstack_endpoint,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test'
            )
            
            # List buckets
            response = s3.list_buckets()
            buckets = [bucket['Name'] for bucket in response.get('Buckets', [])]
            
            if 'bitcoin-data-lake' in buckets:
                print(f"   ✅ bitcoin-data-lake bucket exists")
                return True
            else:
                print(f"   ❌ bitcoin-data-lake bucket missing")
                return False
                
        except Exception as e:
            print(f"   ❌ S3 test failed: {e}")
            return False
    
    async def test_redis_connection(self) -> bool:
        """Test Redis connection"""
        
        print("🔴 Testing Redis connection...")
        
        try:
            import redis
            
            r = redis.Redis(host='localhost', port=6379, decode_responses=True)
            
            # Test ping
            if r.ping():
                print(f"   ✅ Redis connection successful")
                
                # Test set/get
                test_key = "test:pipeline"
                test_value = "e2e_test"
                r.set(test_key, test_value, ex=60)
                
                retrieved = r.get(test_key)
                if retrieved == test_value:
                    print(f"   ✅ Redis read/write working")
                    r.delete(test_key)
                    return True
                else:
                    print(f"   ❌ Redis read/write failed")
                    return False
            else:
                print(f"   ❌ Redis ping failed")
                return False
                
        except Exception as e:
            print(f"   ❌ Redis test failed: {e}")
            return False
    
    async def test_data_flow(self, duration: int = 60) -> bool:
        """Test actual data flow through the pipeline"""
        
        print(f"📊 Testing data flow for {duration} seconds...")
        
        try:
            import boto3
            import redis
            
            # Setup clients
            kinesis = boto3.client(
                'kinesis',
                endpoint_url=self.localstack_endpoint,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test'
            )
            
            s3 = boto3.client(
                's3',
                endpoint_url=self.localstack_endpoint,
                region_name='us-east-1',
                aws_access_key_id='test',
                aws_secret_access_key='test'
            )
            
            r = redis.Redis(host='localhost', port=6379, decode_responses=True)
            
            # Wait for data to flow
            print(f"   ⏳ Waiting {duration}s for data collection...")
            await asyncio.sleep(duration)
            
            # Check Kinesis for records
            kinesis_records = 0
            streams = ['market-trade-stream', 'market-bestbidask-stream', 'market-depth-stream']
            
            for stream in streams:
                try:
                    response = kinesis.describe_stream(StreamName=stream)
                    shards = response['StreamDescription']['Shards']
                    
                    for shard in shards:
                        shard_id = shard['ShardId']
                        iterator_response = kinesis.get_shard_iterator(
                            StreamName=stream,
                            ShardId=shard_id,
                            ShardIteratorType='TRIM_HORIZON'
                        )
                        
                        records_response = kinesis.get_records(
                            ShardIterator=iterator_response['ShardIterator'],
                            Limit=10
                        )
                        
                        records = records_response.get('Records', [])
                        kinesis_records += len(records)
                        
                        if records:
                            print(f"   ✅ {stream}: {len(records)} records found")
                        else:
                            print(f"   ⚠️  {stream}: no records found")
                            
                except Exception as e:
                    print(f"   ❌ Error checking {stream}: {e}")
            
            # Check S3 for files
            s3_objects = 0
            try:
                response = s3.list_objects_v2(Bucket='bitcoin-data-lake')
                s3_objects = response.get('KeyCount', 0)
                
                if s3_objects > 0:
                    print(f"   ✅ S3: {s3_objects} objects found")
                else:
                    print(f"   ⚠️  S3: no objects found")
                    
            except Exception as e:
                print(f"   ❌ Error checking S3: {e}")
            
            # Check Redis for features
            redis_keys = 0
            try:
                feature_keys = r.keys("features:*")
                redis_keys = len(feature_keys)
                
                if redis_keys > 0:
                    print(f"   ✅ Redis: {redis_keys} feature keys found")
                else:
                    print(f"   ⚠️  Redis: no feature keys found")
                    
            except Exception as e:
                print(f"   ❌ Error checking Redis: {e}")
            
            # Determine success
            success = kinesis_records > 0 or s3_objects > 0 or redis_keys > 0
            
            print(f"   📊 Data flow summary:")
            print(f"      Kinesis records: {kinesis_records}")
            print(f"      S3 objects: {s3_objects}")
            print(f"      Redis features: {redis_keys}")
            
            return success
            
        except Exception as e:
            print(f"   ❌ Data flow test failed: {e}")
            return False

async def run_e2e_tests():
    """Run all end-to-end tests"""
    
    print("🧪 Bitcoin Pipeline - End-to-End Tests")
    print("=" * 50)
    
    tester = PipelineE2ETester()
    results = {}
    
    # Test 1: Service Health
    try:
        health_results = await tester.test_service_health()
        results['service_health'] = all(health_results.values())
        
        if not results['service_health']:
            print("❌ Service health check failed - stopping tests")
            return False
            
    except Exception as e:
        print(f"❌ Service health test crashed: {e}")
        results['service_health'] = False
        return False
    
    # Test 2: Infrastructure
    try:
        kinesis_ok = await tester.test_kinesis_streams()
        s3_ok = await tester.test_s3_bucket()
        redis_ok = await tester.test_redis_connection()
        
        results['infrastructure'] = kinesis_ok and s3_ok and redis_ok
        
        if not results['infrastructure']:
            print("❌ Infrastructure test failed - stopping tests")
            return False
            
    except Exception as e:
        print(f"❌ Infrastructure test crashed: {e}")
        results['infrastructure'] = False
        return False
    
    # Test 3: Data Flow
    try:
        data_flow_ok = await tester.test_data_flow(duration=60)
        results['data_flow'] = data_flow_ok
        
    except Exception as e:
        print(f"❌ Data flow test crashed: {e}")
        results['data_flow'] = False
    
    # Summary
    print("\n📊 E2E Test Results:")
    print("=" * 30)
    
    all_passed = True
    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:20} {status}")
        if not success:
            all_passed = False
    
    print("\n" + ("🎉 All E2E tests passed!" if all_passed else "❌ Some E2E tests failed!"))
    return all_passed

if __name__ == "__main__":
    print("🚨 Note: This test requires Docker environment to be running")
    print("🚨 Run: docker-compose -f docker-compose.test.yml up -d")
    print("🚨 Then: ./scripts/setup-localstack.sh")
    print()
    
    success = asyncio.run(run_e2e_tests())
    sys.exit(0 if success else 1)