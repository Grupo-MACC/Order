from sql import crud, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db

async def update_order_status(order_id: int, status: str) -> models.Order|None:
    try:
        async for db in get_db():
            db_order = await crud.update_order_status(db=db, order_id=order_id, status=status)
        return db_order
    except Exception as exc:
        print(exc)
        return None