from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


@dataclass(frozen=True)
class DocumentComponents:
    KnowledgeDocument: type
    KnowledgeDocumentRepository: type
    DocumentStateConflictError: type[Exception]
    DocumentStatus: type


def _document_components() -> DocumentComponents:
    try:
        from app.modules.document.constants import DocumentStatus
        from app.modules.document.exceptions import DocumentStateConflictError
        from app.modules.document.models import KnowledgeDocument
        from app.modules.document.repository import KnowledgeDocumentRepository
    except ModuleNotFoundError as exc:
        pytest.fail(f"document module is missing: {exc}")

    return DocumentComponents(
        KnowledgeDocument=KnowledgeDocument,
        KnowledgeDocumentRepository=KnowledgeDocumentRepository,
        DocumentStateConflictError=DocumentStateConflictError,
        DocumentStatus=DocumentStatus,
    )


def _test_database_url() -> str:
    return get_settings().database_url.replace("@localhost:", "@127.0.0.1:")


@asynccontextmanager
async def _document_session(components: DocumentComponents) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: components.KnowledgeDocument.__table__.create(
                sync_connection,
                checkfirst=True,
            )
        )
        await connection.execute(sa.delete(components.KnowledgeDocument))

    async with session_factory() as session:
        yield session

    async with engine.begin() as connection:
        await connection.execute(sa.delete(components.KnowledgeDocument))

    await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_document_create_and_domain_lifecycle_persist():
    components = _document_components()
    async with _document_session(components) as document_session:
        repository = components.KnowledgeDocumentRepository(document_session)

        document = components.KnowledgeDocument.create(
            doc_title="guide.md",
            upload_user="alice",
            accessible_by="engineering",
        )
        repository.add(document)
        await document_session.commit()
        await document_session.refresh(document)

        assert document.doc_id is not None
        assert document.status == components.DocumentStatus.INIT
        assert document.doc_url is None
        assert document.converted_doc_url is None

        document.mark_uploaded("http://files.test/original/guide.md")
        await document_session.commit()
        await document_session.refresh(document)
        assert document.status == components.DocumentStatus.UPLOADED
        assert document.doc_url == "http://files.test/original/guide.md"

        document.start_converting()
        await document_session.commit()
        await document_session.refresh(document)
        assert document.status == components.DocumentStatus.CONVERTING

        document.mark_converted("http://files.test/converted/document.md")
        await document_session.commit()
        await document_session.refresh(document)
        assert document.status == components.DocumentStatus.CONVERTED
        assert document.converted_doc_url == "http://files.test/converted/document.md"

        document.rollback_to_uploaded()
        await document_session.commit()
        await document_session.refresh(document)
        assert document.status == components.DocumentStatus.UPLOADED
        assert document.converted_doc_url is None


@pytest.mark.asyncio
async def test_repository_start_converting_updates_only_persisted_uploaded_documents(
):
    components = _document_components()
    async with _document_session(components) as document_session:
        repository = components.KnowledgeDocumentRepository(document_session)
        document = components.KnowledgeDocument.create(
            doc_title="paper.pdf",
            upload_user="alice",
            accessible_by="engineering",
        )
        repository.add(document)
        await document_session.commit()
        await document_session.refresh(document)
        await repository.mark_uploaded(document.doc_id, "http://files.test/original/paper.pdf")
        await document_session.commit()

        await repository.start_converting(document.doc_id)
        await document_session.commit()
        await document_session.refresh(document)

        assert document.status == components.DocumentStatus.CONVERTING


@pytest.mark.asyncio
async def test_repository_start_converting_raises_when_expected_state_does_not_match(
):
    components = _document_components()
    async with _document_session(components) as document_session:
        repository = components.KnowledgeDocumentRepository(document_session)
        document = components.KnowledgeDocument.create(
            doc_title="paper.pdf",
            upload_user="alice",
            accessible_by="engineering",
        )
        repository.add(document)
        await document_session.commit()
        await document_session.refresh(document)

        with pytest.raises(components.DocumentStateConflictError):
            await repository.start_converting(document.doc_id)
