# -*- coding: utf-8 -*-
"""Main file to start FastAPI application."""
import logging.config
import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
import asyncio
from routers import order_router, order_router_private, piece_router
from microservice_chassis_grupo2.sql import database, models
from broker import order_broker_service
from saga.broker_saga import saga_broker_service
from microservice_chassis_grupo2.core.consul import create_consul_client

# Configure logging
logging.config.fileConfig(os.path.join(os.path.dirname(__file__), "logging.ini"))
logger = logging.getLogger(__name__)


# App Lifespan
@asynccontextmanager
async def lifespan(__app: FastAPI):
    """Lifespan context manager."""
    consul_client = create_consul_client()
    service_id = os.getenv("SERVICE_ID", "order-1")
    service_name = os.getenv("SERVICE_NAME", "order")
    service_port = int(os.getenv("SERVICE_PORT", 5000))

    try:
        logger.info("Starting up")

        # ✅ PRIMERO: Inicializar la base de datos
        logger.info("Initializing database connection")
        await database.init_database()
        logger.info("Database connection initialized")

        # ✅ SEGUNDO: Crear las tablas
        try:
            logger.info("Creating database tables")
            async with database.engine.begin() as conn:
                await conn.run_sync(models.Base.metadata.create_all)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Could not create tables at startup")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            logger.error(f"Traceback:", exc_info=True)
            # No relances la excepción si quieres que el servicio siga funcionando

        # ✅ TERCERO: Iniciar los consumidores de RabbitMQ
        try:
            task_auth = asyncio.create_task(order_broker_service.consume_auth_events())
            task_delivery = asyncio.create_task(order_broker_service.consume_delivery_events())
            task_machine = asyncio.create_task(order_broker_service.consume_machine_events())
            
            task_payment_saga = asyncio.create_task(saga_broker_service.listen_payment_result())
            task_delivery_saga = asyncio.create_task(saga_broker_service.listen_delivery_result())
            task_money_return_saga = asyncio.create_task(saga_broker_service.listen_money_returned_result())
            
            logger.info("Broker consumers started")
        except Exception as e:
            logger.error(f"Error starting broker service: {e}")

        yield
        
    finally:
        logger.info("Shutting down")
        
        # Cancelar tareas de RabbitMQ
        logger.info("Cancelling broker tasks")
        task_delivery.cancel()
        task_machine.cancel()
        task_auth.cancel()
        task_payment_saga.cancel()
        task_delivery_saga.cancel()
        task_money_return_saga.cancel()
        
        # Cerrar conexión a base de datos
        logger.info("Closing database connection")
        if database.engine:
            await database.engine.dispose()
        
        # Deregistrar de Consul
        result = await consul_client.deregister_service(service_id)
        logger.info(f"✅ Consul service deregistration: {result}")


# OpenAPI Documentation
APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
logger.info("Running app version %s", APP_VERSION)

app = FastAPI(
    redoc_url=None,
    version=APP_VERSION,
    servers=[{"url": "/", "description": "Development"}],
    license_info={
        "name": "MIT License",
        "url": "https://choosealicense.com/licenses/mit/",
    },
    lifespan=lifespan,
)

app.include_router(order_router.router)
app.include_router(piece_router.router)
app.include_router(order_router_private.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)