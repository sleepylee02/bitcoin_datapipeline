"""
Services package for Bitcoin Data Pipeline.

Contains all microservices:
- rest_ingestor: REST API data collection
- sbe_ingestor: SBE WebSocket data streaming  
- aggregator: Real-time data aggregation
- data_connector: S3 to RDBMS data pipeline
- inference: Price prediction service
- trainer: Model training pipeline
"""