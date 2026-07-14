import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationRecorder:
    def __init__(self):
        self.tables: dict[str, tuple] = {}
        self.created_tables: list[str] = []
        self.indexes: list[dict] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name, *elements, **kwargs):
        self.tables[name] = elements
        self.created_tables.append(name)

    def create_index(self, name, table_name, columns, **kwargs):
        self.indexes.append(
            {
                "name": name,
                "table_name": table_name,
                "columns": tuple(columns),
                "kwargs": kwargs,
            }
        )

    def drop_index(self, name, table_name=None, **kwargs):
        self.dropped_indexes.append((name, table_name))

    def drop_table(self, name, **kwargs):
        self.dropped_tables.append(name)


def _load_chat_migration(monkeypatch):
    versions_dir = BACKEND_DIR / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*create_chat_conversation_persistence.py"))
    assert len(migration_files) == 1

    spec = importlib.util.spec_from_file_location(
        "chat_conversation_persistence_migration",
        migration_files[0],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = MigrationRecorder()
    monkeypatch.setattr(module, "op", recorder)
    return module, recorder


def _columns(elements):
    return {
        element.name: element
        for element in elements
        if isinstance(element, sa.Column)
    }


def _constraints(elements, constraint_type):
    return [
        element
        for element in elements
        if isinstance(element, constraint_type)
    ]


def _constraint_column_names(constraint):
    bound_names = tuple(constraint.columns.keys())
    if bound_names:
        return bound_names
    return tuple(
        getattr(column, "name", column)
        for column in getattr(constraint, "_pending_colargs", ())
    )


def _index_column_names(index):
    return tuple(str(column) for column in index["columns"])


def test_chat_migration_revision_follows_current_head(monkeypatch):
    module, _ = _load_chat_migration(monkeypatch)

    assert module.revision == "202607140001"
    assert module.down_revision == "202607080001"


def test_chat_migration_defines_exact_conversation_columns(monkeypatch):
    module, recorder = _load_chat_migration(monkeypatch)
    module.upgrade()

    columns = _columns(recorder.tables["conversations"])
    assert tuple(columns) == (
        "id",
        "user_id",
        "title",
        "status",
        "created_at",
        "updated_at",
    )

    assert isinstance(columns["id"].type, sa.BigInteger)
    assert columns["id"].primary_key is True
    assert columns["id"].identity is None
    assert columns["id"].server_default is None

    assert isinstance(columns["user_id"].type, sa.String)
    assert columns["user_id"].type.length == 255
    assert columns["user_id"].nullable is False

    assert isinstance(columns["title"].type, sa.String)
    assert columns["title"].type.length == 255
    assert columns["title"].nullable is False

    assert isinstance(columns["status"].type, sa.String)
    assert columns["status"].type.length == 32
    assert columns["status"].nullable is False
    assert str(columns["status"].server_default.arg).strip("'") == "ACTIVE"

    for name in ("created_at", "updated_at"):
        assert isinstance(columns[name].type, sa.DateTime)
        assert columns[name].type.timezone is True
        assert columns[name].nullable is False
        assert str(columns[name].server_default.arg) == "CURRENT_TIMESTAMP"


def test_chat_migration_defines_exact_message_columns(monkeypatch):
    module, recorder = _load_chat_migration(monkeypatch)
    module.upgrade()

    columns = _columns(recorder.tables["messages"])
    assert tuple(columns) == (
        "id",
        "conversation_id",
        "parent_message_id",
        "role",
        "content",
        "transformed_content",
        "token_count",
        "model_name",
        "rag_references",
        "metadata",
        "created_at",
        "updated_at",
    )

    assert isinstance(columns["id"].type, sa.BigInteger)
    assert columns["id"].primary_key is True
    assert columns["id"].identity is None
    assert columns["id"].server_default is None

    assert isinstance(columns["conversation_id"].type, sa.BigInteger)
    assert columns["conversation_id"].nullable is False
    conversation_foreign_keys = list(columns["conversation_id"].foreign_keys)
    assert len(conversation_foreign_keys) == 1
    assert conversation_foreign_keys[0].target_fullname == "conversations.id"
    assert conversation_foreign_keys[0].ondelete == "CASCADE"

    assert isinstance(columns["parent_message_id"].type, sa.BigInteger)
    assert columns["parent_message_id"].nullable is True

    assert isinstance(columns["role"].type, sa.String)
    assert columns["role"].type.length == 32
    assert columns["role"].nullable is False

    assert isinstance(columns["content"].type, sa.Text)
    assert columns["content"].nullable is False
    assert isinstance(columns["transformed_content"].type, sa.Text)
    assert columns["transformed_content"].nullable is True
    assert isinstance(columns["token_count"].type, sa.Integer)
    assert columns["token_count"].nullable is True
    assert isinstance(columns["model_name"].type, sa.String)
    assert columns["model_name"].type.length == 255
    assert columns["model_name"].nullable is True

    assert isinstance(columns["rag_references"].type, postgresql.JSONB)
    assert columns["rag_references"].nullable is False
    assert str(columns["rag_references"].server_default.arg) == "'[]'::jsonb"
    assert isinstance(columns["metadata"].type, postgresql.JSONB)
    assert columns["metadata"].nullable is False
    assert str(columns["metadata"].server_default.arg) == "'{}'::jsonb"

    for name in ("created_at", "updated_at"):
        assert isinstance(columns[name].type, sa.DateTime)
        assert columns[name].type.timezone is True
        assert columns[name].nullable is False
        assert str(columns[name].server_default.arg) == "CURRENT_TIMESTAMP"


def test_chat_migration_defines_status_role_and_parent_constraints(monkeypatch):
    module, recorder = _load_chat_migration(monkeypatch)
    module.upgrade()

    conversation_checks = _constraints(
        recorder.tables["conversations"],
        sa.CheckConstraint,
    )
    assert len(conversation_checks) == 1
    conversation_status_sql = str(conversation_checks[0].sqltext)
    assert conversation_checks[0].name == "ck_conversations_status"
    for status in ("ACTIVE", "ARCHIVED", "DELETED"):
        assert status in conversation_status_sql

    message_checks = _constraints(recorder.tables["messages"], sa.CheckConstraint)
    assert len(message_checks) == 1
    message_role_sql = str(message_checks[0].sqltext)
    assert message_checks[0].name == "ck_messages_role"
    assert "USER" in message_role_sql
    assert "ASSISTANT" in message_role_sql
    assert "SYSTEM" not in message_role_sql
    assert "TOOL" not in message_role_sql

    unique_constraints = _constraints(
        recorder.tables["messages"],
        sa.UniqueConstraint,
    )
    assert len(unique_constraints) == 1
    assert unique_constraints[0].name == "uq_messages_conversation_id_id"
    assert _constraint_column_names(unique_constraints[0]) == ("conversation_id", "id")

    foreign_key_constraints = _constraints(
        recorder.tables["messages"],
        sa.ForeignKeyConstraint,
    )
    assert len(foreign_key_constraints) == 1
    parent_constraint = foreign_key_constraints[0]
    assert parent_constraint.name == "fk_messages_parent_same_conversation"
    assert _constraint_column_names(parent_constraint) == (
        "conversation_id",
        "parent_message_id",
    )
    assert tuple(element.target_fullname for element in parent_constraint.elements) == (
        "messages.conversation_id",
        "messages.id",
    )


def test_chat_migration_adds_composite_lookup_indexes(monkeypatch):
    module, recorder = _load_chat_migration(monkeypatch)
    module.upgrade()

    indexes = {index["name"]: index for index in recorder.indexes}
    assert _index_column_names(indexes["ix_conversations_user_status_updated_id"]) == (
        "user_id",
        "status",
        "updated_at DESC",
        "id DESC",
    )
    assert _index_column_names(indexes["ix_messages_conversation_created_id"]) == (
        "conversation_id",
        "created_at",
        "id",
    )
    assert _index_column_names(indexes["ix_messages_conversation_parent"]) == (
        "conversation_id",
        "parent_message_id",
    )


def test_chat_migration_upgrade_and_downgrade_follow_dependency_order(monkeypatch):
    module, recorder = _load_chat_migration(monkeypatch)

    module.upgrade()
    assert recorder.created_tables == ["conversations", "messages"]

    module.downgrade()
    assert recorder.dropped_tables == ["messages", "conversations"]
