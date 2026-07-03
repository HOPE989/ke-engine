from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begins += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.session.transaction_commits += 1
        else:
            self.session.transaction_rollbacks += 1
        return False


class FakeAsyncSession:
    def __init__(self, *, rowcounts=None, scalar_result=None):
        self.added = []
        self.commits = 0
        self.begins = 0
        self.transaction_commits = 0
        self.transaction_rollbacks = 0
        self.refreshes = []
        self.executed = []
        self._rowcounts = list(rowcounts or [1])
        self._scalar_result = scalar_result

    def add(self, instance):
        self.added.append(instance)

    def add_all(self, instances):
        self.added.extend(instances)

    def begin(self):
        return FakeTransaction(self)

    async def commit(self):
        self.commits += 1

    async def refresh(self, instance):
        instance.doc_id = 42
        self.refreshes.append(instance)

    async def execute(self, statement):
        self.executed.append(statement)
        if self._scalar_result is not None:
            return SimpleNamespace(
                rowcount=self._rowcounts.pop(0),
                scalar_one_or_none=lambda: self._scalar_result,
            )
        return SimpleNamespace(rowcount=self._rowcounts.pop(0))


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSessionFactory:
    def __init__(self, *, rowcounts=None, scalar_result=None):
        self.rowcounts = rowcounts
        self.scalar_result = scalar_result
        self.sessions = []

    def __call__(self):
        session = FakeAsyncSession(
            rowcounts=self.rowcounts,
            scalar_result=self.scalar_result,
        )
        self.sessions.append(session)
        return FakeSessionContext(session)


def _compiled_sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _statement_value(statement, column_name):
    for key, value in statement._values.items():
        key_name = getattr(key, "key", key)
        if key_name == column_name:
            return getattr(value, "value", value)
    raise AssertionError(f"{column_name} not set by statement")


def _document_modules():
    from app.modules.document import repository
    from app.modules.document.errors import DocumentStateConflict
    from app.modules.document.models import DocumentStatus, KnowledgeDocument, KnowledgeSegment

    return repository, DocumentStateConflict, DocumentStatus, KnowledgeDocument, KnowledgeSegment


def test_knowledge_document_model_accepts_chunking_statuses_without_schema_drift():
    _, _, DocumentStatus, KnowledgeDocument, _ = _document_modules()

    assert DocumentStatus.CHUNKING.value == "CHUNKING"
    assert DocumentStatus.CHUNKED.value == "CHUNKED"

    columns = KnowledgeDocument.__table__.columns
    assert columns["doc_id"].primary_key is True
    assert columns["doc_id"].identity is None
    assert columns["file_type"].type.length == 32
    assert columns["file_type"].nullable is False

    constraints = [
        constraint
        for constraint in KnowledgeDocument.__table__.constraints
        if constraint.name == "ck_knowledge_document_status"
    ]
    assert len(constraints) == 1
    constraint_sql = str(constraints[0].sqltext)
    assert "CHUNKING" in constraint_sql
    assert "CHUNKED" in constraint_sql


def test_knowledge_segment_model_defines_schema():
    _, _, _, _, KnowledgeSegment = _document_modules()

    columns = KnowledgeSegment.__table__.columns
    assert columns["id"].primary_key is True
    assert columns["id"].identity is None
    assert isinstance(columns["id"].type, sa.BigInteger)

    assert columns["chunk_id"].type.length == 255
    assert columns["chunk_id"].nullable is False

    assert isinstance(columns["text"].type, sa.Text)
    assert columns["text"].nullable is False

    assert columns["document_id"].nullable is False
    foreign_keys = list(columns["document_id"].foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "knowledge_document.doc_id"

    assert columns["chunk_order"].nullable is False
    assert columns["embedding_id"].type.length == 255
    assert columns["embedding_id"].nullable is True

    assert columns["status"].type.length == 255
    assert columns["status"].nullable is False
    assert str(columns["status"].server_default.arg).strip("'") == "INIT"

    assert isinstance(columns["metadata"].type, postgresql.JSONB)
    assert columns["metadata"].nullable is False
    assert columns["skip_embedding"].nullable is False


def test_knowledge_segment_model_adds_lookup_indexes():
    _, _, _, _, KnowledgeSegment = _document_modules()

    indexes_by_columns = {
        tuple(column.name for column in index.columns): index.name
        for index in KnowledgeSegment.__table__.indexes
    }

    assert indexes_by_columns[("document_id",)]
    assert indexes_by_columns[("chunk_id",)]
    assert indexes_by_columns[("status",)]
    assert indexes_by_columns[("chunk_order",)]


@pytest.mark.asyncio
async def test_create_init_document_persists_provided_doc_id_and_file_type():
    repository, _, DocumentStatus, KnowledgeDocument, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    document = await document_repository.create_init_document(
        doc_id=9_007_199_254_740_993,
        doc_title="guide.md",
        upload_user="alice",
        accessible_by="team-a",
        file_type="plain_text",
    )

    session = session_factory.sessions[0]
    assert isinstance(document, KnowledgeDocument)
    assert document.doc_id == 9_007_199_254_740_993
    assert document.doc_title == "guide.md"
    assert document.upload_user == "alice"
    assert document.accessible_by == "team-a"
    assert document.file_type == "plain_text"
    assert document.status == DocumentStatus.INIT.value
    assert session.added == [document]
    assert session.commits == 1
    assert session.refreshes == []


@pytest.mark.asyncio
async def test_get_document_selects_by_doc_id():
    repository, _, _, _, _ = _document_modules()
    document = SimpleNamespace(doc_id=42)
    session_factory = FakeSessionFactory(scalar_result=document)
    document_repository = repository.DocumentRepository(session_factory)

    result = await document_repository.get_document(doc_id=42)

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert "WHERE knowledge_document.doc_id = 42" in _compiled_sql(statement)
    assert result is document


@pytest.mark.asyncio
async def test_mark_uploaded_sets_doc_url_and_moves_from_init_to_uploaded():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.mark_uploaded(
        doc_id=42,
        doc_url="https://files.example.com/documents/42/original/guide.md",
    )

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "doc_url") == (
        "https://files.example.com/documents/42/original/guide.md"
    )
    assert _statement_value(statement, "status") == DocumentStatus.UPLOADED.value
    assert "knowledge_document.status = 'INIT'" in _compiled_sql(statement)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_start_converting_moves_from_uploaded_to_converting():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.start_converting(doc_id=42)

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.CONVERTING.value
    assert "knowledge_document.status = 'UPLOADED'" in _compiled_sql(statement)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_mark_converted_sets_converted_url_from_expected_state():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.mark_converted(
        doc_id=42,
        converted_doc_url="https://files.example.com/documents/42/converted/document.md",
        expected_status=DocumentStatus.CONVERTING,
    )

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "converted_doc_url") == (
        "https://files.example.com/documents/42/converted/document.md"
    )
    assert _statement_value(statement, "status") == DocumentStatus.CONVERTED.value
    assert "knowledge_document.status = 'CONVERTING'" in _compiled_sql(statement)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_rollback_to_uploaded_moves_from_converting_to_uploaded():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.rollback_to_uploaded(doc_id=42)

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.UPLOADED.value
    assert "knowledge_document.status = 'CONVERTING'" in _compiled_sql(statement)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_expected_state_update_raises_state_conflict_on_zero_rows():
    repository, DocumentStateConflict, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory(rowcounts=[0])
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(DocumentStateConflict):
        await document_repository.start_converting(doc_id=42)

    session = session_factory.sessions[0]
    assert session.commits == 0


@pytest.mark.asyncio
async def test_start_chunking_moves_from_converted_to_chunking():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.start_chunking(doc_id=42)

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.CHUNKING.value
    assert "knowledge_document.status = 'CONVERTED'" in _compiled_sql(statement)
    assert session.commits == 1


def _segment_draft(**overrides):
    from app.modules.document.chunking import SegmentDraft

    values = {
        "id": 9001,
        "chunk_id": "10001",
        "text": "chunk text",
        "document_id": 42,
        "chunk_order": 0,
        "embedding_id": None,
        "status": "INIT",
        "metadata": {"chunkId": "10001", "docId": "42"},
        "skip_embedding": False,
    }
    values.update(overrides)
    return SegmentDraft(**values)


@pytest.mark.asyncio
async def test_complete_chunking_inserts_segments_and_marks_chunked_in_one_transaction():
    repository, _, DocumentStatus, _, KnowledgeSegment = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)
    drafts = [
        _segment_draft(),
        _segment_draft(
            id=9002,
            chunk_id="10002",
            text="second",
            chunk_order=1,
            metadata={"chunkId": "10002", "docId": "42"},
        ),
    ]

    await document_repository.complete_chunking(doc_id=42, segment_drafts=drafts)

    session = session_factory.sessions[0]
    assert session.begins == 1
    assert session.transaction_commits == 1
    assert session.transaction_rollbacks == 0
    assert session.commits == 0
    assert len(session.added) == 2
    assert all(isinstance(segment, KnowledgeSegment) for segment in session.added)
    assert [segment.chunk_id for segment in session.added] == ["10001", "10002"]
    assert [segment.metadata_ for segment in session.added] == [
        {"chunkId": "10001", "docId": "42"},
        {"chunkId": "10002", "docId": "42"},
    ]

    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.CHUNKED.value
    assert "knowledge_document.status = 'CHUNKING'" in _compiled_sql(statement)


@pytest.mark.asyncio
async def test_complete_chunking_failure_rolls_back_segment_inserts():
    from app.modules.document.errors import ChunkPersistenceFailed

    repository, _, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory(rowcounts=[0])
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(ChunkPersistenceFailed):
        await document_repository.complete_chunking(
            doc_id=42,
            segment_drafts=[_segment_draft()],
        )

    session = session_factory.sessions[0]
    assert len(session.added) == 1
    assert session.transaction_commits == 0
    assert session.transaction_rollbacks == 1


@pytest.mark.asyncio
async def test_rollback_to_converted_moves_from_chunking_to_converted():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.rollback_to_converted(doc_id=42)

    session = session_factory.sessions[0]
    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.CONVERTED.value
    assert "knowledge_document.status = 'CHUNKING'" in _compiled_sql(statement)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_rollback_to_converted_failure_raises_chunk_rollback_failed():
    from app.modules.document.errors import ChunkRollbackFailed

    repository, _, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory(rowcounts=[0])
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(ChunkRollbackFailed):
        await document_repository.rollback_to_converted(doc_id=42)

    session = session_factory.sessions[0]
    assert session.commits == 0
