import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationRecorder:
    def __init__(self):
        self.tables = {}
        self.indexes = []
        self.dropped_constraints = []
        self.check_constraints = []
        self.altered_columns = []
        self.executed_sql = []

    def create_table(self, name, *elements, **kwargs):
        self.tables[name] = elements

    def create_index(self, name, table_name, columns, **kwargs):
        self.indexes.append(
            {
                "name": name,
                "table_name": table_name,
                "columns": tuple(columns),
                "kwargs": kwargs,
            }
        )

    def drop_constraint(self, name, table_name, **kwargs):
        self.dropped_constraints.append(
            {
                "name": name,
                "table_name": table_name,
                "kwargs": kwargs,
            }
        )

    def create_check_constraint(self, name, table_name, condition, **kwargs):
        self.check_constraints.append(
            {
                "name": name,
                "table_name": table_name,
                "condition": condition,
                "kwargs": kwargs,
            }
        )

    def alter_column(self, table_name, column_name, **kwargs):
        self.altered_columns.append(
            {
                "table_name": table_name,
                "column_name": column_name,
                "kwargs": kwargs,
            }
        )

    def execute(self, statement):
        self.executed_sql.append(statement)


def _load_knowledge_document_migration(monkeypatch):
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    migration_file = versions_dir / "202607010001_create_knowledge_document.py"
    assert migration_file.exists()

    spec = importlib.util.spec_from_file_location(
        "knowledge_document_migration",
        migration_file,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = MigrationRecorder()
    monkeypatch.setattr(module, "op", recorder)
    module.upgrade()
    return recorder


def _load_vector_storage_status_migration(monkeypatch):
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*add_document_vector_storage_status.py"))
    assert len(migration_files) == 1

    spec = importlib.util.spec_from_file_location(
        "document_vector_storage_status_migration",
        migration_files[0],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = MigrationRecorder()
    monkeypatch.setattr(module, "op", recorder)
    module.upgrade()
    return recorder


def test_knowledge_document_migration_defines_exact_columns(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    elements = recorder.tables["knowledge_document"]
    columns = {
        element.name: element
        for element in elements
        if isinstance(element, sa.Column)
    }

    assert isinstance(columns["doc_id"].type, sa.BigInteger)
    assert columns["doc_id"].primary_key is True
    assert columns["doc_id"].identity is None

    assert isinstance(columns["doc_title"].type, sa.String)
    assert columns["doc_title"].type.length == 1024
    assert columns["doc_title"].nullable is False

    assert isinstance(columns["upload_user"].type, sa.String)
    assert columns["upload_user"].type.length == 255
    assert columns["upload_user"].nullable is False

    assert isinstance(columns["doc_url"].type, sa.String)
    assert columns["doc_url"].type.length == 2048
    assert columns["doc_url"].nullable is True

    assert isinstance(columns["file_type"].type, sa.String)
    assert columns["file_type"].type.length == 32
    assert columns["file_type"].nullable is False

    assert isinstance(columns["converted_doc_url"].type, sa.String)
    assert columns["converted_doc_url"].type.length == 2048
    assert columns["converted_doc_url"].nullable is True

    assert isinstance(columns["status"].type, sa.String)
    assert columns["status"].type.length == 32
    assert columns["status"].nullable is False
    assert str(columns["status"].server_default.arg).strip("'") == "INIT"

    assert isinstance(columns["accessible_by"].type, sa.String)
    assert columns["accessible_by"].type.length == 1024
    assert columns["accessible_by"].nullable is False

    for timestamp_column in [columns["created_at"], columns["updated_at"]]:
        assert isinstance(timestamp_column.type, sa.DateTime)
        assert timestamp_column.type.timezone is True
        assert timestamp_column.server_default is not None


def test_knowledge_document_migration_constrains_status(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    constraints = [
        element
        for element in recorder.tables["knowledge_document"]
        if isinstance(element, sa.CheckConstraint)
    ]

    assert len(constraints) == 1
    constraint_sql = str(constraints[0].sqltext)
    for status in [
        "INIT",
        "UPLOADED",
        "CONVERTING",
        "CONVERTED",
        "CHUNKED",
        "VECTOR_STORED",
    ]:
        assert status in constraint_sql
    assert "CHUNKING" not in constraint_sql


def test_knowledge_document_migration_adds_lookup_indexes(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    indexes_by_columns = {
        (index["table_name"], index["columns"]): index["name"]
        for index in recorder.indexes
    }

    assert indexes_by_columns[("knowledge_document", ("status",))]
    assert indexes_by_columns[("knowledge_document", ("upload_user",))]
    assert indexes_by_columns[("knowledge_document", ("created_at",))]


def test_knowledge_segment_migration_defines_columns_and_foreign_key(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    elements = recorder.tables["knowledge_segment"]
    columns = {
        element.name: element
        for element in elements
        if isinstance(element, sa.Column)
    }

    assert isinstance(columns["id"].type, sa.BigInteger)
    assert columns["id"].primary_key is True
    assert columns["id"].identity is None

    assert isinstance(columns["chunk_id"].type, sa.String)
    assert columns["chunk_id"].type.length == 255
    assert columns["chunk_id"].nullable is False

    assert isinstance(columns["text"].type, sa.Text)
    assert columns["text"].nullable is False

    assert isinstance(columns["document_id"].type, sa.BigInteger)
    assert columns["document_id"].nullable is False
    foreign_keys = list(columns["document_id"].foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "knowledge_document.doc_id"

    assert isinstance(columns["chunk_order"].type, sa.Integer)
    assert columns["chunk_order"].nullable is False

    assert isinstance(columns["embedding_id"].type, sa.String)
    assert columns["embedding_id"].type.length == 255
    assert columns["embedding_id"].nullable is True

    assert isinstance(columns["status"].type, sa.String)
    assert columns["status"].type.length == 255
    assert columns["status"].nullable is False
    assert str(columns["status"].server_default.arg).strip("'") == "STORED"

    assert isinstance(columns["metadata"].type, postgresql.JSONB)
    assert columns["metadata"].nullable is False

    assert isinstance(columns["skip_embedding"].type, sa.Boolean)
    assert columns["skip_embedding"].nullable is False


def test_knowledge_segment_migration_adds_lookup_indexes(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    indexes_by_columns = {
        (index["table_name"], index["columns"]): index["name"]
        for index in recorder.indexes
    }

    assert indexes_by_columns[("knowledge_segment", ("document_id",))]
    assert indexes_by_columns[("knowledge_segment", ("chunk_id",))]
    assert indexes_by_columns[("knowledge_segment", ("status",))]
    assert indexes_by_columns[("knowledge_segment", ("chunk_order",))]


def test_vector_storage_status_migration_updates_existing_schema(monkeypatch):
    recorder = _load_vector_storage_status_migration(monkeypatch)

    assert recorder.dropped_constraints == [
        {
            "name": "ck_knowledge_document_status",
            "table_name": "knowledge_document",
            "kwargs": {"type_": "check"},
        }
    ]
    assert recorder.check_constraints == [
        {
            "name": "ck_knowledge_document_status",
            "table_name": "knowledge_document",
            "condition": (
                "status IN ('INIT', 'UPLOADED', 'CONVERTING', 'CONVERTED', "
                "'CHUNKED', 'VECTOR_STORED')"
            ),
            "kwargs": {},
        }
    ]
    assert recorder.altered_columns[0]["table_name"] == "knowledge_segment"
    assert recorder.altered_columns[0]["column_name"] == "status"
    assert str(recorder.altered_columns[0]["kwargs"]["server_default"]).strip("'") == "STORED"
    assert recorder.executed_sql == [
        "UPDATE knowledge_segment SET status = 'STORED' WHERE status = 'INIT'"
    ]
