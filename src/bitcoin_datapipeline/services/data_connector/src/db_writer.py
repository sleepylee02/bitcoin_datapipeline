"""Database writer for PostgreSQL operations."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import asyncpg
from asyncpg import Pool, Connection

from .config.settings import DataConnectorConfig


logger = logging.getLogger(__name__)


class DatabaseWriter:
    """Handles PostgreSQL database operations."""
    
    def __init__(self, config: DataConnectorConfig):
        self.config = config
        self.pool: Optional[Pool] = None
        
        # Statistics
        self.stats = {
            "records_written": 0,
            "batches_written": 0,
            "write_errors": 0,
            "duplicate_skips": 0,
            "last_write_time": None
        }
        
        logger.info("DatabaseWriter initialized")
    
    async def initialize(self):
        """Initialize database connection pool."""
        
        logger.info("Initializing database connection pool")
        
        try:
            # Create connection pool
            self.pool = await asyncpg.create_pool(
                host=self.config.database.host,
                port=self.config.database.port,
                user=self.config.database.user,
                password=self.config.database.password,
                database=self.config.database.name,
                min_size=self.config.database.pool_min_size,
                max_size=self.config.database.pool_max_size,
                command_timeout=60
            )
            
            # Create tables if they don't exist
            await self._create_tables()
            
            logger.info("Database connection pool initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise
    
    async def close(self):
        """Close database connection pool."""
        
        if self.pool:
            logger.info("Closing database connection pool")
            await self.pool.close()
            self.pool = None
    
    async def _create_tables(self):
        """Create database tables if they don't exist."""
        
        async with self.pool.acquire() as conn:
            # Main market data table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id BIGSERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    timestamp BIGINT NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    volume DECIMAL(20,8) NOT NULL,
                    trade_id BIGINT,
                    is_buyer_maker BOOLEAN,
                    source VARCHAR(10) NOT NULL,
                    data_type VARCHAR(20) NOT NULL,
                    ingest_timestamp BIGINT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    
                    -- Additional fields for different data types
                    open_price DECIMAL(20,8),
                    high_price DECIMAL(20,8),
                    low_price DECIMAL(20,8),
                    close_price DECIMAL(20,8),
                    quote_volume DECIMAL(20,8),
                    vwap DECIMAL(20,8),
                    trade_count INTEGER,
                    interval VARCHAR(10),
                    
                    -- Depth data fields
                    best_bid_price DECIMAL(20,8),
                    best_bid_size DECIMAL(20,8),
                    best_ask_price DECIMAL(20,8),
                    best_ask_size DECIMAL(20,8),
                    spread DECIMAL(20,8),
                    mid_price DECIMAL(20,8),
                    last_update_id BIGINT,
                    
                    -- Derived features
                    price_change DECIMAL(20,8),
                    price_change_pct DECIMAL(10,4),
                    hour_of_day INTEGER,
                    day_of_week INTEGER
                ) PARTITION BY RANGE (timestamp)
            """)
            
            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_data_symbol_timestamp 
                ON market_data(symbol, timestamp)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_data_timestamp 
                ON market_data(timestamp)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_data_symbol_data_type 
                ON market_data(symbol, data_type)
            """)
            
            # Create unique constraint to prevent duplicates
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_market_data_unique 
                ON market_data(symbol, timestamp, data_type, COALESCE(trade_id, 0))
            """)
            
            # Create monthly partitions for current and next month
            await self._create_monthly_partitions(conn)
            
            logger.info("Database tables and indexes created successfully")
    
    async def _create_monthly_partitions(self, conn: Connection):
        """Create monthly partitions for better query performance."""
        
        try:
            current_date = datetime.now()
            
            # Create partitions for current and next 3 months
            for i in range(4):
                year = current_date.year
                month = current_date.month + i
                
                # Handle year rollover
                if month > 12:
                    year += (month - 1) // 12
                    month = ((month - 1) % 12) + 1
                
                # Calculate partition bounds
                start_ts = int(datetime(year, month, 1).timestamp() * 1000)
                
                if month == 12:
                    end_ts = int(datetime(year + 1, 1, 1).timestamp() * 1000)
                else:
                    end_ts = int(datetime(year, month + 1, 1).timestamp() * 1000)
                
                partition_name = f"market_data_{year}_{month:02d}"
                
                # Check if partition already exists
                exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_class 
                        WHERE relname = $1
                    )
                """, partition_name)
                
                if not exists:
                    await conn.execute(f"""
                        CREATE TABLE {partition_name} PARTITION OF market_data
                        FOR VALUES FROM ({start_ts}) TO ({end_ts})
                    """)
                    
                    logger.info(f"Created partition {partition_name} for timestamp range {start_ts} to {end_ts}")
                
        except Exception as e:
            logger.warning(f"Error creating partitions: {e}")
    
    async def write_batch(self, records: List[Dict[str, Any]]) -> int:
        """Write a batch of records to the database."""
        
        if not records:
            return 0
        
        logger.debug(f"Writing batch of {len(records)} records")
        
        try:
            async with self.pool.acquire() as conn:
                # Prepare batch insert
                records_written = 0
                
                for record in records:
                    try:
                        await self._insert_record(conn, record)
                        records_written += 1
                        
                    except asyncpg.UniqueViolationError:
                        # Skip duplicates
                        self.stats["duplicate_skips"] += 1
                        logger.debug(f"Skipped duplicate record: {record.get('symbol')} {record.get('timestamp')}")
                        
                    except Exception as e:
                        logger.warning(f"Error inserting record: {e}")
                        self.stats["write_errors"] += 1
                
                # Update statistics
                self.stats["records_written"] += records_written
                self.stats["batches_written"] += 1
                self.stats["last_write_time"] = datetime.now()
                
                logger.debug(f"Successfully wrote {records_written} out of {len(records)} records")
                return records_written
                
        except Exception as e:
            logger.error(f"Error writing batch to database: {e}", exc_info=True)
            self.stats["write_errors"] += 1
            raise
    
    async def _insert_record(self, conn: Connection, record: Dict[str, Any]):
        """Insert a single record into the database."""
        
        # Build INSERT query based on available fields
        fields = []
        values = []
        placeholders = []
        
        # Define field mappings
        field_mappings = {
            'symbol': 'symbol',
            'timestamp': 'timestamp',
            'price': 'price',
            'volume': 'volume',
            'trade_id': 'trade_id',
            'is_buyer_maker': 'is_buyer_maker',
            'source': 'source',
            'data_type': 'data_type',
            'ingest_timestamp': 'ingest_timestamp',
            'open_price': 'open_price',
            'high_price': 'high_price',
            'low_price': 'low_price',
            'close_price': 'close_price',
            'quote_volume': 'quote_volume',
            'vwap': 'vwap',
            'trade_count': 'trade_count',
            'interval': 'interval',
            'best_bid_price': 'best_bid_price',
            'best_bid_size': 'best_bid_size',
            'best_ask_price': 'best_ask_price',
            'best_ask_size': 'best_ask_size',
            'spread': 'spread',
            'mid_price': 'mid_price',
            'last_update_id': 'last_update_id',
            'price_change': 'price_change',
            'price_change_pct': 'price_change_pct',
            'hour_of_day': 'hour_of_day',
            'day_of_week': 'day_of_week'
        }
        
        # Build query components
        for i, (record_key, db_field) in enumerate(field_mappings.items(), 1):
            if record_key in record and record[record_key] is not None:
                fields.append(db_field)
                values.append(record[record_key])
                placeholders.append(f'${i}')
        
        # Always add created_at
        fields.append('created_at')
        values.append(record.get('created_at', datetime.now()))
        placeholders.append(f'${len(values)}')
        
        # Build and execute query
        query = f"""
            INSERT INTO market_data ({', '.join(fields)})
            VALUES ({', '.join(placeholders)})
        """
        
        await conn.execute(query, *values)
    
    async def get_latest_timestamp(self, symbol: str, data_type: str) -> Optional[int]:
        """Get the latest timestamp for a symbol and data type."""
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("""
                    SELECT MAX(timestamp)
                    FROM market_data
                    WHERE symbol = $1 AND data_type = $2
                """, symbol, data_type)
                
                return result
                
        except Exception as e:
            logger.error(f"Error getting latest timestamp: {e}")
            return None
    
    async def get_record_count(self, symbol: Optional[str] = None) -> int:
        """Get total record count, optionally filtered by symbol."""
        
        try:
            async with self.pool.acquire() as conn:
                if symbol:
                    result = await conn.fetchval("""
                        SELECT COUNT(*) FROM market_data WHERE symbol = $1
                    """, symbol)
                else:
                    result = await conn.fetchval("SELECT COUNT(*) FROM market_data")
                
                return result or 0
                
        except Exception as e:
            logger.error(f"Error getting record count: {e}")
            return 0
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on database connection."""
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats.copy()
        }
        
        try:
            if not self.pool:
                health_status["status"] = "unhealthy"
                health_status["error"] = "Database pool not initialized"
                return health_status
            
            # Test database connectivity
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            
            # Check pool status
            pool_stats = {
                "size": self.pool.get_size(),
                "max_size": self.pool.get_max_size(),
                "min_size": self.pool.get_min_size(),
                "idle_size": self.pool.get_idle_size()
            }
            health_status["pool_stats"] = pool_stats
            
            # Check recent activity
            if self.stats["last_write_time"]:
                last_write = self.stats["last_write_time"]
                time_since_write = (datetime.now() - last_write).total_seconds()
                
                if time_since_write > 3600:  # No writes for 1 hour
                    health_status["status"] = "degraded"
                    health_status["warning"] = f"No writes for {time_since_write:.0f} seconds"
            
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database writer statistics."""
        stats = self.stats.copy()
        
        if self.pool:
            stats["pool_stats"] = {
                "size": self.pool.get_size(),
                "max_size": self.pool.get_max_size(),
                "idle_size": self.pool.get_idle_size()
            }
        
        return stats