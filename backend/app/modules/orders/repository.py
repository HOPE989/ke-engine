from sqlalchemy.ext.asyncio import AsyncSession


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

