import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class RecordingOp:
    def __init__(self) -> None:
        self.tables: dict[str, tuple[sa.Column | sa.Constraint, ...]] = {}
        self.indexes: list[tuple[str, str, tuple[str, ...], bool]] = []

    def f(self, name: str) -> str:
        return name

    def create_table(self, name: str, *elements, **kwargs) -> None:
        self.tables[name] = elements

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        unique: bool = False,
    ) -> None:
        self.indexes.append((name, table_name, tuple(columns), unique))


def _run_head_migration() -> RecordingOp:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    revision = scripts.get_revision(heads[0])
    assert revision is not None

    module_spec = importlib.util.spec_from_file_location("document_migration", revision.path)
    assert module_spec is not None
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    module_spec.loader.exec_module(module)

    recorder = RecordingOp()
    module.op = recorder
    module.upgrade()
    return recorder


def _columns(table_elements) -> dict[str, sa.Column]:
    return {
        element.name: element
        for element in table_elements
        if isinstance(element, sa.Column)
    }


def test_knowledge_document_migration_defines_exact_columns_and_defaults():
    recorder = _run_head_migration()
    table = recorder.tables["knowledge_document"]
    columns = _columns(table)

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
    assert str(columns["status"].server_default.arg) == "'INIT'"

    assert isinstance(columns["accessible_by"].type, sa.String)
    assert columns["accessible_by"].type.length == 1024
    assert columns["accessible_by"].nullable is False

    for name in ("created_at", "updated_at"):
        assert isinstance(columns[name].type, sa.DateTime)
        assert columns[name].type.timezone is True
        assert columns[name].server_default is not None


def test_knowledge_document_migration_constrains_status_values():
    recorder = _run_head_migration()
    table = recorder.tables["knowledge_document"]
    checks = [element for element in table if isinstance(element, sa.CheckConstraint)]
    rendered_checks = " ".join(str(check.sqltext) for check in checks)

    for status in ("INIT", "UPLOADED", "CONVERTING", "CONVERTED"):
        assert status in rendered_checks


def test_knowledge_document_migration_adds_lookup_indexes():
    recorder = _run_head_migration()

    assert ("ix_knowledge_document_status", "knowledge_document", ("status",), False) in recorder.indexes
    assert (
        "ix_knowledge_document_upload_user",
        "knowledge_document",
        ("upload_user",),
        False,
    ) in recorder.indexes
    assert (
        "ix_knowledge_document_created_at",
        "knowledge_document",
        ("created_at",),
        False,
    ) in recorder.indexes
