from sql import crud, models
from microservice_chassis_grupo2.core.dependencies import get_db
from sql.database import async_session

async def update_order_status(order_id: int, status: str) -> models.Order|None:
    try:
        async for db in get_db():
            db_order = await crud.update_order_status(db=db, order_id=order_id, status=status)
            return db_order
    except Exception as exc:
        print(exc)
        return None
    
async def update_order_pieces_status(order_id: int, status: str):
    async with async_session() as db:
        try:
            pieces = await crud.get_pieces_by_order(db=db, order_id=order_id)

            db_pieces = []
            for piece in pieces:

                db_piece = await crud.update_piece_status(db=db, piece_id=piece.id, status=status)

                if db_piece:
                    db_pieces.append(db_piece)

            return db_pieces

        except Exception as exc:
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

async def get_order_by_id(order_id: int) -> models.Order | None:
    try:
        async for db in get_db():
            db_order = await crud.get_order(db=db, order_id=order_id)
            return db_order
    except Exception as exc:
        print(exc)
        return None