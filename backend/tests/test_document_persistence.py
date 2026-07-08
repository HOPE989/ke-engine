import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
    def __init__(
        self,
        *,
        rowcounts=None,
        scalar_result=None,
        scalar_results=None,
        scalars_result=None,
    ):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.begins = 0
        self.transaction_commits = 0
        self.transaction_rollbacks = 0
        self.refreshes = []
        self.executed = []
        self.execute_params = []
        self._rowcounts = list(rowcounts or [1])
        self._scalar_result = scalar_result
        self._scalar_results = list(scalar_results or [])
        self._scalars_result = scalars_result

    def add(self, instance):
        self.added.append(instance)

    def add_all(self, instances):
        self.added.extend(instances)

    async def delete(self, instance):
        self.deleted.append(instance)

    def begin(self):
        return FakeTransaction(self)

    async def commit(self):
        self.commits += 1

    async def refresh(self, instance):
        instance.doc_id = 42
        self.refreshes.append(instance)

    async def execute(self, statement, params=None):
        self.executed.append(statement)
        self.execute_params.append(params)
        rowcount = self._rowcounts.pop(0) if self._rowcounts else 1
        scalar_value = (
            self._scalar_results.pop(0)
            if self._scalar_results
            else self._scalar_result
        )
        if self._scalars_result is not None:
            return SimpleNamespace(
                rowcount=rowcount,
                scalars=lambda: SimpleNamespace(all=lambda: self._scalars_result),
            )
        return SimpleNamespace(
            rowcount=rowcount,
            scalar_one_or_none=lambda: scalar_value,
            scalar_one=lambda: scalar_value,
        )


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSessionFactory:
    def __init__(
        self,
        *,
        rowcounts=None,
        scalar_result=None,
        scalar_results=None,
        scalars_result=None,
    ):
        self.rowcounts = rowcounts
        self.scalar_result = scalar_result
        self.scalar_results = scalar_results
        self.scalars_result = scalars_result
        self.sessions = []

    def __call__(self):
        session = FakeAsyncSession(
            rowcounts=self.rowcounts,
            scalar_result=self.scalar_result,
            scalar_results=self.scalar_results,
            scalars_result=self.scalars_result,
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


def test_knowledge_document_model_accepts_chunked_status_without_schema_drift():
    _, _, DocumentStatus, KnowledgeDocument, _ = _document_modules()

    assert DocumentStatus.CHUNKED.value == "CHUNKED"
    assert DocumentStatus.VECTOR_STORED.value == "VECTOR_STORED"
    from app.modules.document.models import KnowledgeBaseType

    assert KnowledgeBaseType.DOCUMENT_SEARCH.value == "DOCUMENT_SEARCH"
    assert KnowledgeBaseType.DATA_QUERY.value == "DATA_QUERY"

    columns = KnowledgeDocument.__table__.columns
    assert columns["doc_id"].primary_key is True
    assert columns["doc_id"].identity is None
    assert isinstance(columns["description"].type, sa.Text)
    assert columns["description"].nullable is False
    assert columns["knowledge_base_type"].type.length == 64
    assert columns["knowledge_base_type"].nullable is False
    assert columns["file_type"].type.length == 32
    assert columns["file_type"].nullable is False

    constraints = [
        constraint
        for constraint in KnowledgeDocument.__table__.constraints
        if constraint.name
        in {"ck_knowledge_document_status", "ck_knowledge_document_knowledge_base_type"}
    ]
    assert len(constraints) == 2
    constraint_sql = "\n".join(str(constraint.sqltext) for constraint in constraints)
    assert "CHUNKED" in constraint_sql
    assert "VECTOR_STORED" in constraint_sql
    assert "DOCUMENT_SEARCH" in constraint_sql
    assert "DATA_QUERY" in constraint_sql

    indexes_by_columns = {
        tuple(column.name for column in index.columns): index.name
        for index in KnowledgeDocument.__table__.indexes
    }
    assert indexes_by_columns[("knowledge_base_type",)]


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
    assert str(columns["status"].server_default.arg).strip("'") == "STORED"

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
        description="Markdown guide",
        knowledge_base_type="DOCUMENT_SEARCH",
        file_type="plain_text",
    )

    session = session_factory.sessions[0]
    assert isinstance(document, KnowledgeDocument)
    assert document.doc_id == 9_007_199_254_740_993
    assert document.doc_title == "guide.md"
    assert document.upload_user == "alice"
    assert document.accessible_by == "team-a"
    assert document.description == "Markdown guide"
    assert document.knowledge_base_type == "DOCUMENT_SEARCH"
    assert document.file_type == "plain_text"
    assert document.status == DocumentStatus.INIT.value
    assert session.added == [document]
    assert session.commits == 1
    assert session.refreshes == []


@pytest.mark.asyncio
async def test_create_data_query_document_with_table_reservation_inserts_document_and_meta():
    from app.modules.document.models import TableMeta

    repository, _, DocumentStatus, KnowledgeDocument, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    document = await document_repository.create_data_query_document_with_table_reservation(
        doc_id=9001,
        table_meta_id=9002,
        doc_title="sales.csv",
        upload_user="alice",
        accessible_by="team-a",
        description="Sales table",
        knowledge_base_type="DATA_QUERY",
        file_type="csv",
        namespace="alice",
        table_name="sales",
        is_override=False,
        extension={"tableName": "sales", "isOverride": False},
    )

    session = session_factory.sessions[0]
    assert session.begins == 1
    assert session.transaction_commits == 1
    assert isinstance(document, KnowledgeDocument)
    assert document.doc_id == 9001
    assert document.extension == {"tableName": "sales", "isOverride": False}
    assert document.status == DocumentStatus.INIT.value
    assert len(session.added) == 2
    assert isinstance(session.added[0], KnowledgeDocument)
    assert isinstance(session.added[1], TableMeta)
    table_meta = session.added[1]
    assert table_meta.id == 9002
    assert table_meta.namespace == "alice"
    assert table_meta.document_id == 9001
    assert table_meta.table_name == "sales"
    assert table_meta.description == "Sales table"
    assert table_meta.create_sql is None
    assert table_meta.columns_info is None


@pytest.mark.asyncio
async def test_create_data_query_document_with_table_reservation_rejects_duplicate_without_override():
    from app.modules.document.errors import DataQueryTableNameConflict
    from app.modules.document.models import TableMeta

    repository, _, _, _, _ = _document_modules()
    existing_meta = TableMeta(
        id=8001,
        namespace="alice",
        document_id=8002,
        table_name="sales",
        description="Old sales",
    )
    session_factory = FakeSessionFactory(scalar_result=existing_meta)
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(DataQueryTableNameConflict):
        await document_repository.create_data_query_document_with_table_reservation(
            doc_id=9001,
            table_meta_id=9002,
            doc_title="sales.csv",
            upload_user="alice",
            accessible_by="team-a",
            description="Sales table",
            knowledge_base_type="DATA_QUERY",
            file_type="csv",
            namespace="alice",
            table_name="sales",
            is_override=False,
            extension={"tableName": "sales", "isOverride": False},
        )

    session = session_factory.sessions[0]
    assert session.transaction_rollbacks == 1
    assert session.added == []
    assert session.deleted == []


@pytest.mark.asyncio
async def test_create_data_query_document_with_table_reservation_overrides_existing_meta():
    from app.modules.document.models import TableMeta

    repository, _, _, KnowledgeDocument, _ = _document_modules()
    existing_meta = TableMeta(
        id=8001,
        namespace="alice",
        document_id=8002,
        table_name="sales",
        description="Old sales",
        columns_info={"physicalTableName": "dq_alice_sales"},
    )
    session_factory = FakeSessionFactory(scalar_result=existing_meta)
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.create_data_query_document_with_table_reservation(
        doc_id=9001,
        table_meta_id=9002,
        doc_title="sales.csv",
        upload_user="alice",
        accessible_by="team-a",
        description="Sales table",
        knowledge_base_type="DATA_QUERY",
        file_type="csv",
        namespace="alice",
        table_name="sales",
        is_override=True,
        extension={"tableName": "sales", "isOverride": True},
    )

    session = session_factory.sessions[0]
    assert "DROP TABLE IF EXISTS" in str(session.executed[1])
    assert '"dq_alice_sales"' in str(session.executed[1])
    assert session.deleted == [existing_meta]
    assert any(isinstance(instance, KnowledgeDocument) for instance in session.added)
    assert any(isinstance(instance, TableMeta) and instance.document_id == 9001 for instance in session.added)


@pytest.mark.asyncio
async def test_delete_data_query_reservation_deletes_by_document_id():
    repository, _, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory()
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.delete_data_query_reservation(document_id=9001)

    session = session_factory.sessions[0]
    sql = _compiled_sql(session.executed[0])
    assert "DELETE FROM table_meta" in sql
    assert "table_meta.document_id = 9001" in sql
    assert session.commits == 1


@pytest.mark.asyncio
async def test_get_table_meta_by_document_selects_by_document_id():
    from app.modules.document.models import TableMeta

    repository, _, _, _, _ = _document_modules()
    table_meta = TableMeta(
        id=9002,
        namespace="alice",
        document_id=9001,
        table_name="sales",
        description="Sales table",
    )
    session_factory = FakeSessionFactory(scalar_result=table_meta)
    document_repository = repository.DocumentRepository(session_factory)

    result = await document_repository.get_table_meta_by_document(document_id=9001)

    session = session_factory.sessions[0]
    assert result is table_meta
    assert "WHERE table_meta.document_id = 9001" in _compiled_sql(session.executed[0])


@pytest.mark.asyncio
async def test_import_data_query_table_creates_rows_metadata_and_marks_document_stored():
    from app.modules.document.models import DocumentStatus, TableMeta

    repository, _, _, _, _ = _document_modules()
    table_meta = TableMeta(
        id=9002,
        namespace="alice",
        document_id=9001,
        table_name="sales",
        description="Sales table",
    )
    session_factory = FakeSessionFactory(
        scalar_results=[table_meta, None],
        rowcounts=[1, 1],
    )
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.import_data_query_table(
        document_id=9001,
        physical_table_name="dq_abc123_sales",
        create_sql='CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)',
        columns_info={
            "originalSheetName": "Data",
            "physicalTableName": "dq_abc123_sales",
            "columns": [{"ordinal": 1, "header": "Customer", "columnName": "col_001", "type": "TEXT"}],
        },
        column_names=["col_001"],
        rows=[["Alice"], ["Bob"]],
    )

    session = session_factory.sessions[0]
    assert session.transaction_commits == 1
    assert session.transaction_rollbacks == 0
    assert str(session.executed[2]) == 'CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)'
    assert "INSERT INTO" in str(session.executed[3])
    assert session.execute_params[3] == [{"col_001": "Alice"}, {"col_001": "Bob"}]
    table_meta_update = session.executed[4]
    assert _statement_value(table_meta_update, "create_sql") == (
        'CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)'
    )
    document_update = session.executed[5]
    assert _statement_value(document_update, "status") == DocumentStatus.STORED.value
    assert "knowledge_document.status = 'UPLOADED'" in _compiled_sql(document_update)


@pytest.mark.asyncio
async def test_import_data_query_table_inserts_rows_in_batches(monkeypatch):
    from app.modules.document.models import TableMeta

    repository, _, _, _, _ = _document_modules()
    monkeypatch.setattr(repository, "DATA_QUERY_INSERT_BATCH_SIZE", 2)
    table_meta = TableMeta(
        id=9002,
        namespace="alice",
        document_id=9001,
        table_name="sales",
        description="Sales table",
    )
    session_factory = FakeSessionFactory(
        scalar_results=[table_meta, None],
    )
    document_repository = repository.DocumentRepository(session_factory)

    await document_repository.import_data_query_table(
        document_id=9001,
        physical_table_name="dq_abc123_sales",
        create_sql='CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)',
        columns_info={"physicalTableName": "dq_abc123_sales", "columns": []},
        column_names=["col_001"],
        rows=[["A"], ["B"], ["C"], ["D"], ["E"]],
    )

    session = session_factory.sessions[0]
    insert_params = [
        params
        for statement, params in zip(session.executed, session.execute_params, strict=True)
        if "INSERT INTO" in str(statement)
    ]
    assert insert_params == [
        [{"col_001": "A"}, {"col_001": "B"}],
        [{"col_001": "C"}, {"col_001": "D"}],
        [{"col_001": "E"}],
    ]


@pytest.mark.asyncio
async def test_import_data_query_table_rolls_back_when_document_cannot_be_marked_stored():
    from app.modules.document.errors import DataQueryIngestionFailed
    from app.modules.document.models import TableMeta

    repository, _, _, _, _ = _document_modules()
    table_meta = TableMeta(
        id=9002,
        namespace="alice",
        document_id=9001,
        table_name="sales",
        description="Sales table",
    )
    session_factory = FakeSessionFactory(
        scalar_results=[table_meta, None],
        rowcounts=[1, 1, 1, 1, 1, 0],
    )
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(DataQueryIngestionFailed):
        await document_repository.import_data_query_table(
            document_id=9001,
            physical_table_name="dq_abc123_sales",
            create_sql='CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)',
            columns_info={"physicalTableName": "dq_abc123_sales", "columns": []},
            column_names=["col_001"],
            rows=[["Alice"], ["Bob"]],
        )

    session = session_factory.sessions[0]
    assert session.transaction_commits == 0
    assert session.transaction_rollbacks == 1
    assert any("CREATE TABLE" in str(statement) for statement in session.executed)
    assert any("INSERT INTO" in str(statement) for statement in session.executed)
    insert_index = next(
        index for index, statement in enumerate(session.executed) if "INSERT INTO" in str(statement)
    )
    assert session.execute_params[insert_index] == [{"col_001": "Alice"}, {"col_001": "Bob"}]


@pytest.mark.asyncio
async def test_import_data_query_table_rejects_existing_physical_table_without_drop():
    from app.modules.document.errors import DataQueryIngestionFailed
    from app.modules.document.models import TableMeta

    repository, _, _, _, _ = _document_modules()
    table_meta = TableMeta(
        id=9002,
        namespace="alice",
        document_id=9001,
        table_name="sales",
        description="Sales table",
    )
    session_factory = FakeSessionFactory(
        scalar_results=[table_meta, "dq_abc123_sales"],
    )
    document_repository = repository.DocumentRepository(session_factory)

    with pytest.raises(DataQueryIngestionFailed):
        await document_repository.import_data_query_table(
            document_id=9001,
            physical_table_name="dq_abc123_sales",
            create_sql='CREATE TABLE "dq_abc123_sales" ("col_001" TEXT)',
            columns_info={"physicalTableName": "dq_abc123_sales", "columns": []},
            column_names=["col_001"],
            rows=[["Alice"]],
        )

    session = session_factory.sessions[0]
    assert session.transaction_rollbacks == 1
    executed_sql = "\n".join(str(statement) for statement in session.executed)
    assert "DROP TABLE" not in executed_sql
    assert "INSERT INTO" not in executed_sql


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
async def test_list_stale_chunked_document_ids_filters_by_status_cutoff_and_orders():
    repository, _, _, _, _ = _document_modules()
    session_factory = FakeSessionFactory(scalars_result=[1001, 1002])
    document_repository = repository.DocumentRepository(session_factory)

    result = await document_repository.list_stale_chunked_document_ids(
        older_than=timedelta(minutes=5)
    )

    session = session_factory.sessions[0]
    statement = session.executed[0]
    sql = _compiled_sql(statement)
    assert result == [1001, 1002]
    assert "SELECT knowledge_document.doc_id" in sql
    assert "knowledge_document.status = 'CHUNKED'" in sql
    assert "knowledge_document.updated_at <" in sql
    assert "ORDER BY knowledge_document.updated_at ASC, knowledge_document.doc_id ASC" in sql


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


def _segment_draft(**overrides):
    from app.modules.document.chunking import SegmentDraft

    values = {
        "id": 9001,
        "chunk_id": "10001",
        "text": "chunk text",
        "document_id": 42,
        "chunk_order": 0,
        "embedding_id": None,
        "status": "STORED",
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
    assert [segment.status for segment in session.added] == ["STORED", "STORED"]
    assert [segment.metadata_ for segment in session.added] == [
        {"chunkId": "10001", "docId": "42"},
        {"chunkId": "10002", "docId": "42"},
    ]

    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.CHUNKED.value
    assert "knowledge_document.status = 'CONVERTED'" in _compiled_sql(statement)


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
async def test_complete_chunking_rolls_back_inserted_segments_on_postgres_stale_chunked_state():
    database_url = os.environ.get("DOCUMENT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set DOCUMENT_TEST_DATABASE_URL to run PostgreSQL transaction integration tests")

    from app.db.base import Base
    from app.modules.document.errors import ChunkPersistenceFailed
    from app.modules.document.repository import DocumentRepository

    _, _, DocumentStatus, KnowledgeDocument, KnowledgeSegment = _document_modules()

    schema_name = f"test_doc_chunk_{uuid4().hex}"
    bootstrap_engine = create_async_engine(database_url)
    async with bootstrap_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    await bootstrap_engine.dispose()

    engine = create_async_engine(database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'SET search_path TO "{schema_name}"')
        finally:
            cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        doc_id = 424242
        async with session_factory() as session:
            session.add(
                KnowledgeDocument(
                    doc_id=doc_id,
                    doc_title="chunked.md",
                    upload_user="tester",
                    accessible_by="team-a",
                    description="Chunked document",
                    knowledge_base_type="DOCUMENT_SEARCH",
                    file_type="markdown",
                    converted_doc_url=(
                        "https://files.example.com/documents/documents/424242/converted/document.md"
                    ),
                    status=DocumentStatus.CHUNKED.value,
                )
            )
            await session.commit()

        repository = DocumentRepository(session_factory)
        with pytest.raises(ChunkPersistenceFailed):
            await repository.complete_chunking(
                doc_id=doc_id,
                segment_drafts=[_segment_draft(document_id=doc_id)],
            )

        async with session_factory() as session:
            segment_count = await session.scalar(
                sa.select(sa.func.count())
                .select_from(KnowledgeSegment)
                .where(KnowledgeSegment.document_id == doc_id)
            )
            status = await session.scalar(
                sa.select(KnowledgeDocument.status).where(KnowledgeDocument.doc_id == doc_id)
            )

        assert segment_count == 0
        assert status == DocumentStatus.CHUNKED.value
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_import_data_query_table_rolls_back_dynamic_table_on_postgres_failure():
    database_url = os.environ.get("DOCUMENT_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set DOCUMENT_TEST_DATABASE_URL to run PostgreSQL transaction integration tests")

    from app.db.base import Base
    from app.modules.document.errors import DataQueryIngestionFailed
    from app.modules.document.models import DocumentStatus, KnowledgeDocument, TableMeta
    from app.modules.document.repository import DocumentRepository

    schema_name = f"test_data_query_import_{uuid4().hex}"
    bootstrap_engine = create_async_engine(database_url)
    async with bootstrap_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    await bootstrap_engine.dispose()

    engine = create_async_engine(database_url)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'SET search_path TO "{schema_name}"')
        finally:
            cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        doc_id = 525252
        physical_table_name = "dq_abc123abc123_sales"
        async with session_factory() as session:
            session.add(
                KnowledgeDocument(
                    doc_id=doc_id,
                    doc_title="sales.csv",
                    upload_user="tester",
                    accessible_by="team-a",
                    description="Sales data",
                    knowledge_base_type="DATA_QUERY",
                    extension={"tableName": "sales", "isOverride": False},
                    file_type="csv",
                    status=DocumentStatus.CONVERTED.value,
                )
            )
            session.add(
                TableMeta(
                    id=625252,
                    namespace="tester",
                    document_id=doc_id,
                    table_name="sales",
                    description="Sales data",
                )
            )
            await session.commit()

        repository = DocumentRepository(session_factory)
        with pytest.raises(DataQueryIngestionFailed):
            await repository.import_data_query_table(
                document_id=doc_id,
                physical_table_name=physical_table_name,
                create_sql=f'CREATE TABLE "{physical_table_name}" ("col_001" TEXT)',
                columns_info={
                    "originalSheetName": "Data",
                    "physicalTableName": physical_table_name,
                    "columns": [
                        {
                            "ordinal": 1,
                            "header": "Customer",
                            "columnName": "col_001",
                            "type": "TEXT",
                        }
                    ],
                },
                column_names=["col_001"],
                rows=[["Alice"]],
            )

        async with session_factory() as session:
            exists_result = await session.execute(
                text("SELECT to_regclass(:table_name)"),
                {"table_name": physical_table_name},
            )
            document_status = await session.scalar(
                sa.select(KnowledgeDocument.status).where(KnowledgeDocument.doc_id == doc_id)
            )
            metadata_result = await session.execute(
                sa.select(TableMeta.create_sql, TableMeta.columns_info).where(
                    TableMeta.document_id == doc_id
                )
            )
            create_sql, columns_info = metadata_result.one()

        assert exists_result.scalar_one() is None
        assert document_status == DocumentStatus.CONVERTED.value
        assert create_sql is None
        assert columns_info is None
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_list_pending_embeddable_segments_uses_fixed_first_page_ordering():
    repository, _, _, _, _ = _document_modules()
    segments = [SimpleNamespace(id=9001), SimpleNamespace(id=9002)]
    session = FakeAsyncSession(scalars_result=segments)
    document_repository = repository.DocumentRepository(FakeSessionFactory())

    result = await document_repository.list_pending_embeddable_segments(
        session=session,
        doc_id=42,
    )

    statement = session.executed[0]
    sql = _compiled_sql(statement)
    assert result == segments
    assert "knowledge_segment.document_id = 42" in sql
    assert "knowledge_segment.status = 'STORED'" in sql
    assert "knowledge_segment.skip_embedding IS false" in sql
    assert "knowledge_segment.embedding_id IS NULL" in sql
    assert "ORDER BY knowledge_segment.chunk_order ASC, knowledge_segment.id ASC" in sql
    assert "LIMIT 100" in sql
    assert "OFFSET" not in sql


@pytest.mark.asyncio
async def test_mark_segments_vector_stored_updates_embedding_ids_and_status_without_commit():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session = FakeAsyncSession(rowcounts=[1, 1])
    document_repository = repository.DocumentRepository(FakeSessionFactory())

    await document_repository.mark_segments_vector_stored(
        session=session,
        segment_embedding_ids={9001: "es-id-1", 9002: "es-id-2"},
    )

    assert len(session.executed) == 2
    assert [_statement_value(statement, "embedding_id") for statement in session.executed] == [
        "es-id-1",
        "es-id-2",
    ]
    assert [_statement_value(statement, "status") for statement in session.executed] == [
        DocumentStatus.VECTOR_STORED.value,
        DocumentStatus.VECTOR_STORED.value,
    ]
    assert "knowledge_segment.id = 9001" in _compiled_sql(session.executed[0])
    assert "knowledge_segment.id = 9002" in _compiled_sql(session.executed[1])
    assert session.commits == 0


@pytest.mark.asyncio
async def test_count_pending_embeddable_segments_double_checks_remaining_rows():
    repository, _, _, _, _ = _document_modules()
    session = FakeAsyncSession(scalar_result=3)
    document_repository = repository.DocumentRepository(FakeSessionFactory())

    count = await document_repository.count_pending_embeddable_segments(
        session=session,
        doc_id=42,
    )

    sql = _compiled_sql(session.executed[0])
    assert count == 3
    assert "knowledge_segment.document_id = 42" in sql
    assert "knowledge_segment.status = 'STORED'" in sql
    assert "knowledge_segment.skip_embedding IS false" in sql
    assert "knowledge_segment.embedding_id IS NULL" in sql
    assert session.commits == 0


@pytest.mark.asyncio
async def test_mark_document_vector_stored_completes_chunked_document_without_commit():
    repository, _, DocumentStatus, _, _ = _document_modules()
    session = FakeAsyncSession()
    document_repository = repository.DocumentRepository(FakeSessionFactory())

    await document_repository.mark_document_vector_stored(session=session, doc_id=42)

    statement = session.executed[0]
    assert _statement_value(statement, "status") == DocumentStatus.VECTOR_STORED.value
    sql = _compiled_sql(statement)
    assert "knowledge_document.doc_id = 42" in sql
    assert "knowledge_document.status = 'CHUNKED'" in sql
    assert session.commits == 0


