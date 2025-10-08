"""Deduplication utilities for preventing duplicate records."""

import time
from typing import Dict, Any, Set
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)


class RecordDeduplicator:
    """
    Record deduplicator to prevent duplicate data ingestion.
    
    Features:
    - Time-based window deduplication
    - LRU-style memory management
    - Per-symbol tracking
    - Configurable retention periods
    """
    
    def __init__(
        self,
        window_size_seconds: int = 3600,  # 1 hour
        max_records_per_symbol: int = 100000,
        cleanup_interval_seconds: int = 300  # 5 minutes
    ):
        self.window_size_seconds = window_size_seconds
        self.max_records_per_symbol = max_records_per_symbol
        self.cleanup_interval_seconds = cleanup_interval_seconds
        
        # Track seen records: symbol -> {record_id: timestamp}
        self._seen_records: Dict[str, Dict[str, float]] = defaultdict(dict)
        
        # Track insertion order for LRU cleanup: symbol -> deque of (record_id, timestamp)
        self._insertion_order: Dict[str, deque] = defaultdict(deque)
        
        # Last cleanup time
        self._last_cleanup = time.time()
        
        # Statistics
        self.stats = {
            'total_checks': 0,
            'duplicates_found': 0,
            'unique_records': 0,
            'cleanup_runs': 0,
            'records_cleaned': 0
        }
        
        logger.info(
            f"RecordDeduplicator initialized: window={window_size_seconds}s, "
            f"max_per_symbol={max_records_per_symbol}"
        )
    
    def is_unique(self, record_id: str, timestamp: int, symbol: str = "default") -> bool:
        """
        Check if a record is unique within the deduplication window.
        
        Args:
            record_id: Unique identifier for the record
            timestamp: Record timestamp (milliseconds)
            symbol: Symbol to group records by (default: "default")
        
        Returns:
            True if record is unique, False if duplicate
        """
        
        self.stats['total_checks'] += 1
        
        # Perform cleanup if needed
        current_time = time.time()
        if current_time - self._last_cleanup > self.cleanup_interval_seconds:
            self._cleanup_old_records()
        
        # Convert timestamp to seconds for window comparison
        record_time = timestamp / 1000.0 if timestamp > 1e10 else timestamp
        
        # Check if we've seen this record recently
        if record_id in self._seen_records[symbol]:
            existing_time = self._seen_records[symbol][record_id]
            
            # If within the window, it's a duplicate
            if current_time - existing_time < self.window_size_seconds:
                self.stats['duplicates_found'] += 1
                logger.debug(f"Duplicate record found: {record_id} for {symbol}")
                return False
            else:
                # Outside window, update the timestamp
                self._seen_records[symbol][record_id] = current_time
                # Remove from old position in insertion order and add to end
                self._update_insertion_order(symbol, record_id, current_time)
                self.stats['unique_records'] += 1
                return True
        else:
            # New record
            self._seen_records[symbol][record_id] = current_time
            self._insertion_order[symbol].append((record_id, current_time))
            
            # Check if we need to trim for memory management
            if len(self._seen_records[symbol]) > self.max_records_per_symbol:
                self._trim_symbol_records(symbol)
            
            self.stats['unique_records'] += 1
            return True
    
    def _update_insertion_order(self, symbol: str, record_id: str, timestamp: float):
        """Update insertion order for an existing record."""
        
        # Remove old entry (inefficient but necessary for correctness)
        # In practice, this is rare as most updates are for old records outside the window
        insertion_queue = self._insertion_order[symbol]
        new_queue = deque()
        
        for existing_id, existing_ts in insertion_queue:
            if existing_id != record_id:
                new_queue.append((existing_id, existing_ts))
        
        # Add updated entry at the end
        new_queue.append((record_id, timestamp))
        self._insertion_order[symbol] = new_queue
    
    def _trim_symbol_records(self, symbol: str):
        """Remove oldest records for a symbol to stay within memory limits."""
        
        records_to_remove = len(self._seen_records[symbol]) - self.max_records_per_symbol
        if records_to_remove <= 0:
            return
        
        insertion_queue = self._insertion_order[symbol]
        
        # Remove oldest records
        removed_count = 0
        while insertion_queue and removed_count < records_to_remove:
            record_id, _ = insertion_queue.popleft()
            if record_id in self._seen_records[symbol]:
                del self._seen_records[symbol][record_id]
                removed_count += 1
        
        self.stats['records_cleaned'] += removed_count
        logger.debug(f"Trimmed {removed_count} old records for {symbol}")
    
    def _cleanup_old_records(self):
        """Remove records outside the time window."""
        
        current_time = time.time()
        cutoff_time = current_time - self.window_size_seconds
        
        total_cleaned = 0
        
        for symbol in list(self._seen_records.keys()):\n            # Clean seen_records\n            records_to_remove = [\n                record_id for record_id, timestamp in self._seen_records[symbol].items()\n                if timestamp < cutoff_time\n            ]\n            \n            for record_id in records_to_remove:\n                del self._seen_records[symbol][record_id]\n            \n            # Clean insertion_order\n            insertion_queue = self._insertion_order[symbol]\n            new_queue = deque()\n            \n            for record_id, timestamp in insertion_queue:\n                if timestamp >= cutoff_time:\n                    new_queue.append((record_id, timestamp))\n            \n            self._insertion_order[symbol] = new_queue\n            \n            cleaned_count = len(records_to_remove)\n            total_cleaned += cleaned_count\n            \n            # Remove empty symbol entries\n            if not self._seen_records[symbol]:\n                del self._seen_records[symbol]\n                del self._insertion_order[symbol]\n        \n        self._last_cleanup = current_time\n        self.stats['cleanup_runs'] += 1\n        self.stats['records_cleaned'] += total_cleaned\n        \n        if total_cleaned > 0:\n            logger.debug(f\"Cleaned {total_cleaned} old records across all symbols\")\n    \n    def force_cleanup(self):\n        \"\"\"Force immediate cleanup of old records.\"\"\"\n        self._cleanup_old_records()\n    \n    def clear_symbol(self, symbol: str):\n        \"\"\"Clear all records for a specific symbol.\"\"\"\n        if symbol in self._seen_records:\n            count = len(self._seen_records[symbol])\n            del self._seen_records[symbol]\n            del self._insertion_order[symbol]\n            logger.info(f\"Cleared {count} records for symbol {symbol}\")\n    \n    def clear_all(self):\n        \"\"\"Clear all deduplication state.\"\"\"\n        total_records = sum(len(records) for records in self._seen_records.values())\n        self._seen_records.clear()\n        self._insertion_order.clear()\n        logger.info(f\"Cleared all {total_records} deduplication records\")\n    \n    def get_stats(self) -> Dict[str, Any]:\n        \"\"\"Get deduplication statistics.\"\"\"\n        \n        symbol_counts = {\n            symbol: len(records)\n            for symbol, records in self._seen_records.items()\n        }\n        \n        total_records = sum(symbol_counts.values())\n        duplicate_rate = 0.0\n        if self.stats['total_checks'] > 0:\n            duplicate_rate = self.stats['duplicates_found'] / self.stats['total_checks']\n        \n        return {\n            **self.stats,\n            'duplicate_rate': duplicate_rate,\n            'total_tracked_records': total_records,\n            'symbol_counts': symbol_counts,\n            'memory_usage_mb': self._estimate_memory_usage(),\n            'window_size_seconds': self.window_size_seconds,\n            'last_cleanup_age_seconds': time.time() - self._last_cleanup\n        }\n    \n    def _estimate_memory_usage(self) -> float:\n        \"\"\"Estimate memory usage in MB (rough approximation).\"\"\"\n        \n        # Rough estimate: each record ID + timestamp + overhead\n        # Average record ID length ~50 chars, timestamp 8 bytes, Python overhead ~100 bytes\n        bytes_per_record = 50 + 8 + 100\n        \n        total_records = sum(len(records) for records in self._seen_records.values())\n        estimated_bytes = total_records * bytes_per_record\n        \n        return estimated_bytes / (1024 * 1024)  # Convert to MB\n    \n    def health_check(self) -> Dict[str, Any]:\n        \"\"\"Perform health check on deduplicator.\"\"\"\n        \n        stats = self.get_stats()\n        \n        health_status = {\n            'healthy': True,\n            'issues': []\n        }\n        \n        # Check memory usage\n        if stats['memory_usage_mb'] > 100:  # >100MB\n            health_status['healthy'] = False\n            health_status['issues'].append(f\"High memory usage: {stats['memory_usage_mb']:.1f}MB\")\n        \n        # Check duplicate rate\n        if stats['duplicate_rate'] > 0.5:  # >50% duplicates\n            health_status['healthy'] = False\n            health_status['issues'].append(f\"High duplicate rate: {stats['duplicate_rate']:.2%}\")\n        \n        # Check cleanup frequency\n        if stats['last_cleanup_age_seconds'] > self.cleanup_interval_seconds * 2:\n            health_status['healthy'] = False\n            health_status['issues'].append(\"Cleanup overdue\")\n        \n        return {\n            'status': 'healthy' if health_status['healthy'] else 'unhealthy',\n            'issues': health_status['issues'],\n            'stats': stats\n        }"