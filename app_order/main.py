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
# Configure logging ################################################################################
logging.config.fileConfig(os.path.join(os.path.dirname(__file__), "logging.ini"))
logger = logging.getLogger(__name__)


# App Lifespan #####################################################################################
@asynccontextmanager
async def lifespan(__app: FastAPI):
    """Lifespan context manager."""
    try:
        logger.info("Starting up")
        try:
            logger.info("Creating database tables")
            async with database.engine.begin() as conn:
                await conn.run_sync(models.Base.metadata.create_all)
        except Exception:
            logger.error(
                "Could not create tables at startup",
            )

        try:
            #task_payment = asyncio.create_task(order_broker_service.consume_payment_events())
            task_auth = asyncio.create_task(order_broker_service.consume_auth_events())
            task_delivery = asyncio.create_task(order_broker_service.consume_delivery_events())
            task_machine = asyncio.create_task(order_broker_service.consume_machine_events())
            
            task_payment_saga = asyncio.create_task(saga_broker_service.listen_payment_result())
            task_delivery_saga = asyncio.create_task(saga_broker_service.listen_delivery_result())
            tesk_money_return_saga = asyncio.create_task(saga_broker_service.listen_money_returned_result())
        except Exception as e:
            logger.error(f"Error lanzando broker service: {e}")

        yield
    finally:
        logger.info("Shutting down database")
        await database.engine.dispose()
        logger.info("Shutting down rabbitmq")
        #task_payment.cancel()
        task_delivery.cancel()
        task_machine.cancel()
        task_auth.cancel()
        
        task_payment_saga.cancel()
        task_delivery_saga.cancel()
        tesk_money_return_saga.cancel()


# OpenAPI Documentation ############################################################################
APP_VERSION = os.getenv("APP_VERSION", "2.0.0")
logger.info("Running app version %s", APP_VERSION)

app = FastAPI(
    redoc_url=None,  # disable redoc documentation.
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

#python -m uvicorn main:app --reload --port 5000