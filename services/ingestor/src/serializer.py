# Avro Serializer for Market Data

# TODO: Load Avro schema from schemas/avro/market_data.avsc
# - Support loading schema from file path
# - Cache compiled schema for performance
# - Validate schema on startup

# TODO: Implement serialization functions
# - serialize_market_data(data: dict) -> bytes
#   - Validate input data against schema
#   - Serialize to Avro binary format
#   - Return bytes for Kinesis
# - deserialize_market_data(data: bytes) -> dict
#   - For testing and validation purposes

# TODO: Handle schema evolution
# - Support backward/forward compatibility
# - Log schema version in metadata
# - Handle missing optional fields gracefully

# TODO: Error handling
# - Schema validation errors
# - Type conversion errors
# - Missing required fields
