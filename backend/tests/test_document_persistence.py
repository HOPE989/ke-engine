from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql


class FakeAsyncSession:
    def __init__(self, *, rowcounts=None):
        self.added = []
        self.commits = 0
        self.refreshes = []
        self.executed = []
        self._rowcounts = list(rowcounts or [1])

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        self.commits += 1

    async def refresh(self, instance):
        instance.doc_id = 42
        self.refreshes.append(instance)

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=self._rowcounts.pop(0))


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSessionFactory:
    def __init__(self, *, rowcounts=None):
        self.rowcounts = rowcounts
        self.sessions = []

    def __call__(self):
        session = FakeAsyncSession(rowcounts=self.rowcounts)
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
    from app.modules.document.models import DocumentStatus, KnowledgeDocument

    return repository, DocumentStateConflict, DocumentStatus, KnowledgeDocument


@pytest.mark.asyncio
async def test_create_init_document_commits_and_refreshes_generated_doc_id():
    repository, _, DocumentStatus, KnowledgeDocument = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    document = await document_repository.create_init_document(
        doc_title="guide.md",
        upload_user="alice",
        accessible_by="team-a",
    )

    session = session_factory.sessions[0]
    assert isinstance(document, KnowledgeDocument)
    assert document.doc_id == 42
    assert document.doc_title == "guide.md"
    assert document.upload_user == "alice"
    assert document.accessible_by == "team-a"
    assert document.status == DocumentStatus.INIT.value
    assert session.added == [document]
    assert session.commits == 1
    assert session.refreshes == [document]


@pytest.mark.asyncio
async def test_mark_uploaded_sets_doc_url_and_moves_from_init_to_uploaded():
    repository, _, DocumentStatus, _ = _document_modules()
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
    repository, _, DocumentStatus, _ = _document_modules()
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
    repository, _, DocumentStatus, _ = _document_modules()
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
    repository, _, DocumentStatus, _ = _document_modules()
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
    repository, DocumentStateConflict, _, _ = _document_modules()
    session_factory = FakeSessionFactory(rowcounts=[0])
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(DocumentStateConflict):
        await document_repository.start_converting(doc_id=42)

    session = session_factory.sessions[0]
    assert session.commits == 0
