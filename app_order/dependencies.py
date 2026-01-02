# -*- coding: utf-8 -*-
"""Application dependency injector."""
import logging
from sql.database import async_session

logger = logging.getLogger(__name__)

async def get_db():
    """
    Provee una AsyncSession.

    - No commit automático.
    - Rollback y re-lanzar excepciones.
    """
    async with async_session() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise