import importlib.util
from pathlib import Path

import sqlalchemy as sa


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationRecorder:
    def __init__(self):
        self.tables = {}
        self.indexes = []

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


def _load_knowledge_document_migration(monkeypatch):
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    migration_files = [
        path
        for path in versions_dir.glob("*.py")
        if "knowledge_document" in path.read_text(encoding="utf-8")
    ]
    assert len(migration_files) == 1

    spec = importlib.util.spec_from_file_location(
        "knowledge_document_migration",
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
    assert columns["doc_id"].identity is not None

    assert isinstance(columns["doc_title"].type, sa.String)
    assert columns["doc_title"].type.length == 1024
    assert columns["doc_title"].nullable is False

    assert isinstance(columns["upload_user"].type, sa.String)
    assert columns["upload_user"].type.length == 255
    assert columns["upload_user"].nullable is False

    assert isinstance(columns["doc_url"].type, sa.String)
    assert columns["doc_url"].type.length == 2048
    assert columns["doc_url"].nullable is True

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
    for status in ["INIT", "UPLOADED", "CONVERTING", "CONVERTED"]:
        assert status in constraint_sql


def test_knowledge_document_migration_adds_lookup_indexes(monkeypatch):
    recorder = _load_knowledge_document_migration(monkeypatch)

    indexes_by_columns = {
        (index["table_name"], index["columns"]): index["name"]
        for index in recorder.indexes
    }

    assert indexes_by_columns[("knowledge_document", ("status",))]
    assert indexes_by_columns[("knowledge_document", ("upload_user",))]
    assert indexes_by_columns[("knowledge_document", ("created_at",))]
