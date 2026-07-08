"""data-query table 仓储入口。"""

from app.domains.document.repositories.document_repository import DocumentRepository


class TableRepository(DocumentRepository):
    """Table 仓储视图。

    当前复用 `DocumentRepository` 的 session 与既有方法；后续可以逐步把 table
    专属方法物理移动到这里。
    """
