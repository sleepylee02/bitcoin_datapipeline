"""Health check endpoint for REST ingestor service."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from aiohttp import web, web_request
from aiohttp.web_response import Response

from .main import RestIngestorService


logger = logging.getLogger(__name__)


class HealthCheckHandler:
    """Health check HTTP handler."""
    
    def __init__(self, service: RestIngestorService):
        self.service = service
    
    async def health(self, request: web_request.Request) -> Response:
        """Basic health check endpoint."""
        try:
            health_data = await self.service.health_check()
            
            # Determine HTTP status based on health
            status = 200 if health_data["status"] == "healthy" else 503
            
            return web.json_response(health_data, status=status)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return web.json_response(
                {
                    "service": "rest-ingestor",
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                },
                status=503
            )
    
    async def ready(self, request: web_request.Request) -> Response:
        """Readiness probe for Kubernetes."""
        try:
            health_data = await self.service.health_check()
            
            # Service is ready if it's healthy or degraded
            is_ready = health_data["status"] in ["healthy", "degraded"]
            status = 200 if is_ready else 503
            
            return web.json_response(
                {
                    "ready": is_ready,
                    "status": health_data["status"],
                    "timestamp": datetime.utcnow().isoformat()
                },
                status=status
            )
            
        except Exception as e:
            logger.error(f"Readiness check failed: {e}", exc_info=True)
            return web.json_response(
                {
                    "ready": False,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                },
                status=503
            )
    
    async def live(self, request: web_request.Request) -> Response:
        """Liveness probe for Kubernetes."""
        # Simple liveness check - just return OK if service is running
        return web.json_response(
            {
                "alive": True,
                "timestamp": datetime.utcnow().isoformat()
            },
            status=200
        )


class HealthCheckServer:
    """HTTP server for health check endpoints."""
    
    def __init__(self, service: RestIngestorService, host: str = "0.0.0.0", port: int = 8080):
        self.service = service
        self.host = host
        self.port = port
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
    async def start(self):
        """Start the health check server."""
        logger.info(f"Starting health check server on {self.host}:{self.port}")
        
        # Create aiohttp application
        self.app = web.Application()
        
        # Setup routes
        handler = HealthCheckHandler(self.service)
        self.app.router.add_get('/health', handler.health)
        self.app.router.add_get('/ready', handler.ready)
        self.app.router.add_get('/live', handler.live)
        
        # Add CORS headers for development
        self.app.middlewares.append(self._cors_middleware)
        
        # Start server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        
        logger.info(f"Health check server started on http://{self.host}:{self.port}")
    
    async def stop(self):
        """Stop the health check server."""
        logger.info("Stopping health check server")
        
        if self.site:
            await self.site.stop()
        
        if self.runner:
            await self.runner.cleanup()
        
        logger.info("Health check server stopped")
    
    @web.middleware
    async def _cors_middleware(self, request: web_request.Request, handler):
        """CORS middleware for development."""
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response