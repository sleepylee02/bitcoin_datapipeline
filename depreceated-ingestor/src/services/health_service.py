"""Health check service for monitoring service status."""

import asyncio
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, Response
import uvicorn

from ..config.settings import HealthConfig

logger = logging.getLogger(__name__)


class HealthService:
    """
    HTTP health check service.
    
    Provides endpoints for:
    - Basic health check
    - Detailed service status
    - Component-specific health
    """
    
    def __init__(self, config: HealthConfig, ingest_service):
        self.config = config
        self.ingest_service = ingest_service
        
        # FastAPI app
        self.app = FastAPI(
            title="Bitcoin Ingestor Health Service",
            description="Health check endpoints for the Bitcoin data ingestor",
            version="1.0.0"
        )
        
        self.server: Optional[uvicorn.Server] = None
        self.server_task: Optional[asyncio.Task] = None
        
        self._setup_routes()
        
        logger.info(f"HealthService initialized on {config.host}:{config.port}")
    
    def _setup_routes(self):
        """Setup health check routes."""
        
        @self.app.get("/health")
        async def health_check():
            """Basic health check endpoint."""
            try:
                health_data = await self.ingest_service.health_check()
                
                if health_data['status'] == 'healthy':
                    return {
                        "status": "healthy",
                        "timestamp": datetime.utcnow().isoformat() + 'Z',
                        "service": "bitcoin-ingestor"
                    }
                else:
                    return Response(
                        content=json.dumps({
                            "status": "unhealthy",
                            "timestamp": datetime.utcnow().isoformat() + 'Z',
                            "service": "bitcoin-ingestor",
                            "issues": health_data['overall']['issues']
                        }),
                        status_code=503,
                        media_type="application/json"
                    )
            
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return Response(
                    content=json.dumps({
                        "status": "error",
                        "timestamp": datetime.utcnow().isoformat() + 'Z',
                        "service": "bitcoin-ingestor",
                        "error": str(e)
                    }),
                    status_code=500,
                    media_type="application/json"
                )
        
        @self.app.get("/health/detailed")
        async def detailed_health():
            """Detailed health check with component status."""
            try:
                health_data = await self.ingest_service.health_check()
                
                response_data = {
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "service": "bitcoin-ingestor",
                    "overall_status": health_data['status'],
                    "components": health_data['components'],
                    "stats": health_data['stats']
                }
                
                status_code = 200 if health_data['status'] == 'healthy' else 503
                
                return Response(
                    content=json.dumps(response_data, default=str),
                    status_code=status_code,
                    media_type="application/json"
                )
            
            except Exception as e:
                logger.error(f"Detailed health check failed: {e}")
                return Response(
                    content=json.dumps({
                        "status": "error",
                        "timestamp": datetime.utcnow().isoformat() + 'Z',
                        "service": "bitcoin-ingestor",
                        "error": str(e)
                    }),
                    status_code=500,
                    media_type="application/json"
                )
        
        @self.app.get("/health/components/{component}")
        async def component_health(component: str):
            """Health check for a specific component."""
            try:
                health_data = await self.ingest_service.health_check()
                
                if component not in health_data['components']:
                    return Response(
                        content=json.dumps({
                            "error": f"Component '{component}' not found",
                            "available_components": list(health_data['components'].keys())
                        }),
                        status_code=404,
                        media_type="application/json"
                    )
                
                component_health = health_data['components'][component]
                
                response_data = {
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "component": component,
                    "status": component_health['status'],
                    "details": component_health
                }
                
                status_code = 200 if component_health['status'] == 'healthy' else 503
                
                return Response(
                    content=json.dumps(response_data, default=str),
                    status_code=status_code,
                    media_type="application/json"
                )
            
            except Exception as e:
                logger.error(f"Component health check failed for {component}: {e}")
                return Response(
                    content=json.dumps({
                        "status": "error",
                        "component": component,
                        "error": str(e)
                    }),
                    status_code=500,
                    media_type="application/json"
                )
        
        @self.app.get("/stats")
        async def service_stats():
            """Get service statistics."""
            try:
                stats = self.ingest_service.get_stats()
                
                return {
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "stats": stats
                }
            
            except Exception as e:
                logger.error(f"Stats endpoint failed: {e}")
                return Response(
                    content=json.dumps({
                        "error": str(e),
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    }),
                    status_code=500,
                    media_type="application/json"
                )
        
        @self.app.get("/")
        async def root():
            """Root endpoint with service info."""
            return {
                "service": "bitcoin-ingestor",
                "version": "1.0.0",
                "description": "Bitcoin market data ingestion service",
                "endpoints": {
                    "health": "/health",
                    "detailed_health": "/health/detailed",
                    "component_health": "/health/components/{component}",
                    "stats": "/stats"
                },
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            }
    
    async def start(self):
        """Start the health check HTTP server."""
        try:
            config = uvicorn.Config(
                app=self.app,
                host=self.config.host,
                port=self.config.port,
                log_level="warning",  # Reduce uvicorn noise
                access_log=False
            )
            
            self.server = uvicorn.Server(config)
            self.server_task = asyncio.create_task(self.server.serve())
            
            # Wait a moment for server to start
            await asyncio.sleep(0.1)
            
            logger.info(f"Health service started on http://{self.config.host}:{self.config.port}")
            
        except Exception as e:
            logger.error(f"Failed to start health service: {e}")
            raise
    
    async def stop(self):
        """Stop the health check HTTP server."""
        if self.server:
            self.server.should_exit = True
        
        if self.server_task and not self.server_task.done():
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Health service stopped")
    
    def is_running(self) -> bool:
        """Check if the health service is running."""
        return (
            self.server_task is not None and
            not self.server_task.done() and
            not self.server_task.cancelled()
        )