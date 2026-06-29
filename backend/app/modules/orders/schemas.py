from decimal import Decimal

from pydantic import BaseModel


class OrderRead(BaseModel):
    id: int
    user_id: int
    amount: Decimal
    status: str

