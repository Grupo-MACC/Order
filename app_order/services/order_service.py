from sql import crud, models, schemas
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db
from broker import order_broker_service

async def update_order_status(order_id: int, status: str) -> models.Order|None:
    try:
        async for db in get_db():
            db_order = await crud.update_order_status(db=db, order_id=order_id, status=status)
            if status == models.Order.STATUS_PAID:
                try:
                    
                    await order_broker_service.publish_order_paid(order_id)
                except Exception as net_exc:
                    print(net_exc)
                print("Order %s finished successfully.", order_id)

        return db_order
    except Exception as exc:
        print(exc)
        return None