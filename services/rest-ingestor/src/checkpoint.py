"""Checkpoint manager for resumable data collection."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from .config.settings import RestIngestorConfig
from .config.aws_config import AWSClientManager


logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Checkpoint data structure."""
    symbol: str
    last_timestamp: int
    last_collection_time: str
    total_records: int = 0
    collection_stats: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.collection_stats is None:
            self.collection_stats = {}


class CheckpointManager:
    """Manages collection checkpoints for resumable operations."""
    
    def __init__(self, config: RestIngestorConfig):
        self.config = config
        self.aws_client_manager = AWSClientManager(config.aws)
        self.storage_type = config.checkpoint.storage_type
        self.local_checkpoint_dir = config.checkpoint.local_directory
        
        logger.info(f"CheckpointManager initialized with storage: {self.storage_type}")
    
    async def get_checkpoint(self, symbol: str) -> Optional[Checkpoint]:
        """Get the latest checkpoint for a symbol."""
        try:
            if self.storage_type == "s3":
                return await self._get_checkpoint_from_s3(symbol)
            else:
                return await self._get_checkpoint_from_local(symbol)
        except Exception as e:
            logger.error(f"Failed to get checkpoint for {symbol}: {e}")
            return None
    
    async def save_checkpoint(
        self, 
        symbol: str, 
        timestamp: int, 
        collection_stats: Dict[str, Any]
    ):
        """Save a checkpoint for a symbol."""
        checkpoint = Checkpoint(
            symbol=symbol,
            last_timestamp=timestamp,
            last_collection_time=datetime.utcnow().isoformat(),
            total_records=sum(
                stats.get("records_collected", 0) 
                for stats in collection_stats.values()
            ),
            collection_stats=collection_stats
        )
        
        try:
            if self.storage_type == "s3":
                await self._save_checkpoint_to_s3(checkpoint)
            else:
                await self._save_checkpoint_to_local(checkpoint)
            
            logger.info(f"Checkpoint saved for {symbol} at timestamp {timestamp}")
            
        except Exception as e:
            logger.error(f"Failed to save checkpoint for {symbol}: {e}")
    
    async def _get_checkpoint_from_s3(self, symbol: str) -> Optional[Checkpoint]:
        """Get checkpoint from S3."""
        checkpoint_key = f"{self.config.aws.s3_checkpoint_prefix}/{symbol}/checkpoint.json"
        
        try:
            s3_client = self.aws_client_manager.s3_client
            
            # Use asyncio executor for blocking S3 call
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: s3_client.get_object(
                    Bucket=self.config.aws.s3_bucket,
                    Key=checkpoint_key
                )
            )
            
            checkpoint_data = json.loads(response['Body'].read().decode('utf-8'))
            return Checkpoint(**checkpoint_data)
            
        except s3_client.exceptions.NoSuchKey:
            logger.info(f"No existing checkpoint found for {symbol}")
            return None
        except Exception as e:
            logger.error(f"Error reading checkpoint from S3 for {symbol}: {e}")
            return None
    
    async def _save_checkpoint_to_s3(self, checkpoint: Checkpoint):
        """Save checkpoint to S3."""
        checkpoint_key = f"{self.config.aws.s3_checkpoint_prefix}/{checkpoint.symbol}/checkpoint.json"
        checkpoint_data = json.dumps(asdict(checkpoint), indent=2)
        
        s3_client = self.aws_client_manager.s3_client
        
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: s3_client.put_object(
                Bucket=self.config.aws.s3_bucket,
                Key=checkpoint_key,
                Body=checkpoint_data.encode('utf-8'),
                ContentType='application/json'
            )
        )
    
    async def _get_checkpoint_from_local(self, symbol: str) -> Optional[Checkpoint]:
        """Get checkpoint from local file."""
        import os
        
        checkpoint_file = os.path.join(
            self.local_checkpoint_dir, 
            f"{symbol}_checkpoint.json"
        )
        
        try:
            if os.path.exists(checkpoint_file):
                with open(checkpoint_file, 'r') as f:
                    checkpoint_data = json.load(f)
                return Checkpoint(**checkpoint_data)
            else:
                logger.info(f"No existing local checkpoint found for {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Error reading local checkpoint for {symbol}: {e}")
            return None
    
    async def _save_checkpoint_to_local(self, checkpoint: Checkpoint):
        """Save checkpoint to local file."""
        import os
        
        # Ensure checkpoint directory exists
        os.makedirs(self.local_checkpoint_dir, exist_ok=True)
        
        checkpoint_file = os.path.join(
            self.local_checkpoint_dir, 
            f"{checkpoint.symbol}_checkpoint.json"
        )
        
        checkpoint_data = asdict(checkpoint)
        
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)
    
    async def list_checkpoints(self) -> Dict[str, Checkpoint]:
        """List all available checkpoints."""
        checkpoints = {}
        
        try:
            if self.storage_type == "s3":
                checkpoints = await self._list_checkpoints_from_s3()
            else:
                checkpoints = await self._list_checkpoints_from_local()
                
        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}")
        
        return checkpoints
    
    async def _list_checkpoints_from_s3(self) -> Dict[str, Checkpoint]:
        """List checkpoints from S3."""
        checkpoints = {}
        
        try:
            s3_client = self.aws_client_manager.s3_client
            prefix = f"{self.config.aws.s3_checkpoint_prefix}/"
            
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: s3_client.list_objects_v2(
                    Bucket=self.config.aws.s3_bucket,
                    Prefix=prefix
                )
            )
            
            for obj in response.get('Contents', []):
                if obj['Key'].endswith('/checkpoint.json'):
                    # Extract symbol from key
                    symbol = obj['Key'].replace(prefix, '').replace('/checkpoint.json', '')
                    checkpoint = await self._get_checkpoint_from_s3(symbol)
                    if checkpoint:
                        checkpoints[symbol] = checkpoint
                        
        except Exception as e:
            logger.error(f"Error listing S3 checkpoints: {e}")
        
        return checkpoints
    
    async def _list_checkpoints_from_local(self) -> Dict[str, Checkpoint]:
        """List checkpoints from local directory."""
        import os
        import glob
        
        checkpoints = {}
        
        try:
            if os.path.exists(self.local_checkpoint_dir):
                pattern = os.path.join(self.local_checkpoint_dir, "*_checkpoint.json")
                
                for checkpoint_file in glob.glob(pattern):
                    # Extract symbol from filename
                    filename = os.path.basename(checkpoint_file)
                    symbol = filename.replace('_checkpoint.json', '')
                    
                    checkpoint = await self._get_checkpoint_from_local(symbol)
                    if checkpoint:
                        checkpoints[symbol] = checkpoint
                        
        except Exception as e:
            logger.error(f"Error listing local checkpoints: {e}")
        
        return checkpoints
    
    async def cleanup_old_checkpoints(self, days_old: int = 30):
        """Clean up checkpoints older than specified days."""
        try:
            cutoff_date = datetime.utcnow().timestamp() - (days_old * 24 * 3600)
            checkpoints = await self.list_checkpoints()
            
            for symbol, checkpoint in checkpoints.items():
                checkpoint_time = datetime.fromisoformat(
                    checkpoint.last_collection_time.replace('Z', '+00:00')
                ).timestamp()
                
                if checkpoint_time < cutoff_date:
                    logger.info(f"Cleaning up old checkpoint for {symbol}")
                    await self._delete_checkpoint(symbol)
                    
        except Exception as e:
            logger.error(f"Error cleaning up old checkpoints: {e}")
    
    async def _delete_checkpoint(self, symbol: str):
        """Delete a checkpoint."""
        try:
            if self.storage_type == "s3":
                checkpoint_key = f"{self.config.aws.s3_checkpoint_prefix}/{symbol}/checkpoint.json"
                s3_client = self.aws_client_manager.s3_client
                
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: s3_client.delete_object(
                        Bucket=self.config.aws.s3_bucket,
                        Key=checkpoint_key
                    )
                )
            else:
                import os
                checkpoint_file = os.path.join(
                    self.local_checkpoint_dir, 
                    f"{symbol}_checkpoint.json"
                )
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)
                    
        except Exception as e:
            logger.error(f"Error deleting checkpoint for {symbol}: {e}")