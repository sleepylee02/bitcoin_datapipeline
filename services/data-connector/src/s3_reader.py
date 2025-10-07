"""S3 reader for discovering and reading bronze layer data."""

import asyncio
import json
import gzip
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError

from .config.settings import DataConnectorConfig


logger = logging.getLogger(__name__)


class S3Reader:
    """Reads data from S3 bronze layer."""
    
    def __init__(self, config: DataConnectorConfig):
        self.config = config
        
        # Initialize S3 client
        session = boto3.Session()
        self.s3_client = session.client(
            's3',
            region_name=config.aws.region,
            endpoint_url=config.aws.endpoint_url
        )
        
        # Processed files tracking (in production, this would be in a database)
        self._processed_files = set()
        
        logger.info(f"S3Reader initialized for bucket: {config.aws.s3_bucket}")
    
    async def discover_new_files(
        self, 
        last_processed_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Discover new files in S3 bronze layer."""
        
        if not last_processed_time:
            # Default to last 24 hours
            last_processed_time = datetime.now() - timedelta(hours=24)
        
        logger.info(f"Discovering files newer than {last_processed_time}")
        
        try:
            files_to_process = []
            
            # Search for files in bronze layer
            prefix = f"{self.config.aws.s3_bronze_prefix}/"
            
            # Use asyncio executor for blocking S3 calls
            paginator = self.s3_client.get_paginator('list_objects_v2')
            
            async for page in self._paginate_s3_objects(paginator, prefix):
                for obj in page.get('Contents', []):
                    file_info = await self._process_s3_object(obj, last_processed_time)
                    if file_info:
                        files_to_process.append(file_info)
            
            # Sort by last modified time
            files_to_process.sort(key=lambda x: x['last_modified'])
            
            logger.info(f"Found {len(files_to_process)} new files to process")
            return files_to_process
            
        except Exception as e:
            logger.error(f"Error discovering S3 files: {e}", exc_info=True)
            raise
    
    async def _paginate_s3_objects(self, paginator, prefix: str):
        """Async iterator for S3 object pagination."""
        page_iterator = paginator.paginate(
            Bucket=self.config.aws.s3_bucket,
            Prefix=prefix
        )
        
        for page in page_iterator:
            yield page
    
    async def _process_s3_object(
        self, 
        s3_object: Dict[str, Any], 
        last_processed_time: datetime
    ) -> Optional[Dict[str, Any]]:
        """Process S3 object and determine if it should be processed."""
        
        key = s3_object['Key']
        last_modified = s3_object['LastModified'].replace(tzinfo=None)
        
        # Skip if already processed
        if key in self._processed_files:
            return None
        
        # Skip if too old
        if last_modified <= last_processed_time:
            return None
        
        # Skip non-data files
        if not self._is_data_file(key):
            return None
        
        # Extract metadata from key
        metadata = self._extract_metadata_from_key(key)
        
        return {
            "key": key,
            "last_modified": last_modified,
            "size": s3_object['Size'],
            "symbol": metadata.get("symbol"),
            "data_type": metadata.get("data_type"),
            "partition_info": metadata.get("partition_info")
        }
    
    def _is_data_file(self, key: str) -> bool:
        """Check if S3 key represents a data file."""
        # Check for expected data file patterns
        data_patterns = ['.jsonl', '.jsonl.gz', '.json', '.json.gz']
        return any(key.endswith(pattern) for pattern in data_patterns)
    
    def _extract_metadata_from_key(self, key: str) -> Dict[str, Any]:
        """Extract metadata from S3 key path."""
        # Example key: bronze/BTCUSDT/aggTrades/year=2024/month=01/day=15/hour=14/aggTrades_20240115_140000.jsonl.gz
        
        parts = key.split('/')
        metadata = {}
        
        try:
            # Extract symbol (assuming it's the second part after bronze/)
            if len(parts) >= 2 and parts[0] == self.config.aws.s3_bronze_prefix:
                metadata["symbol"] = parts[1]
            
            # Extract data type
            if len(parts) >= 3:
                metadata["data_type"] = parts[2]
            
            # Extract partition information
            partition_info = {}
            for part in parts:
                if '=' in part:
                    k, v = part.split('=', 1)
                    partition_info[k] = v
            
            metadata["partition_info"] = partition_info
            
        except Exception as e:
            logger.warning(f"Could not extract metadata from key {key}: {e}")
        
        return metadata
    
    async def read_file(self, file_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read and parse data from S3 file."""
        
        key = file_info["key"]
        logger.debug(f"Reading file: {key}")
        
        try:
            # Download file from S3
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.get_object(
                    Bucket=self.config.aws.s3_bucket,
                    Key=key
                )
            )
            
            # Read file content
            content = response['Body'].read()
            
            # Decompress if gzipped
            if key.endswith('.gz'):
                content = gzip.decompress(content)
            
            # Parse JSONL content
            content_str = content.decode('utf-8')
            records = []
            
            for line in content_str.strip().split('\n'):
                if line.strip():
                    try:
                        record = json.loads(line)
                        records.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON line in {key}: {e}")
            
            # Mark file as processed
            self._processed_files.add(key)
            
            logger.debug(f"Read {len(records)} records from {key}")
            return records
            
        except Exception as e:
            logger.error(f"Error reading file {key}: {e}", exc_info=True)
            raise
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on S3 reader."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "bucket": self.config.aws.s3_bucket,
            "processed_files_count": len(self._processed_files)
        }
        
        try:
            # Test S3 connectivity
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.head_bucket(Bucket=self.config.aws.s3_bucket)
            )
            
            health_status["s3_connectivity"] = "ok"
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                health_status["status"] = "unhealthy"
                health_status["error"] = f"Bucket {self.config.aws.s3_bucket} not found"
            elif error_code == '403':
                health_status["status"] = "unhealthy"
                health_status["error"] = "Access denied to S3 bucket"
            else:
                health_status["status"] = "degraded"
                health_status["error"] = f"S3 error: {error_code}"
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
        
        return health_status
    
    def get_processed_files_count(self) -> int:
        """Get count of processed files."""
        return len(self._processed_files)
    
    def reset_processed_files(self):
        """Reset processed files tracking (for testing)."""
        self._processed_files.clear()
        logger.info("Reset processed files tracking")