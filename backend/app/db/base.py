import sys

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


if "app.modules.document.models" not in sys.modules:
    from app.modules.document.models import KnowledgeDocument  # noqa: E402,F401
