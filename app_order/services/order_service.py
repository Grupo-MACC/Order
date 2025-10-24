from sql import crud, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db
from broker import order_broker_service

async def update_order_status(order_id: int, status: str) -> models.Order|None:
    try:
        async for db in get_db():
            db_order = await crud.update_order_status(db=db, order_id=order_id, status=status)
            return db_order
    except Exception as exc:
        print(exc)
        return None
    
async def update_piece_status(piece_id: int, status: str) -> models.Piece | None:
    try:
        async for db in get_db():
            db_piece = await crud.update_piece_status(db=db, piece_id=piece_id, status=status)

        return db_piece
    except Exception as exc:
        print(f"Error actualizando el estado de la pieza {piece_id}: {exc}")
        return None

async def update_piece_manufacturing_date_to_now(piece_id: int) -> models.Piece | None:
    try:
        async for db in get_db():
            db_piece = await crud.update_piece_manufacturing_date_to_now(db=db, piece_id=piece_id)

        return db_piece
    except Exception as exc:
        print(f"Error actualizando el estado de la pieza {piece_id}: {exc}")
        return None