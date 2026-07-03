from pathlib import Path


def test_root_makefile_exposes_backend_dev_targets():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "dev-api:" in content
    assert "dev-worker:" in content
    assert "dev-infra:" in content
    assert "$(UV) run uvicorn app.main:app --reload" in content
    assert "$(UV) run python -m app.workers.kafka_worker" in content
    assert "docker compose up -d postgres redis minio kafka" in content
    assert "kafka-topics-init:" in content
    assert "kafka-topics-list:" in content
    assert "kafka-topics.sh" in content
    assert "--create" in content
    assert "--if-not-exists" in content
    assert "--topic document.convert.requested" in content


def test_root_makefile_exposes_database_init_target():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "db-init:" in content
    assert "make db-init" in content
    assert "Reset local database and upgrade schema to head" in content
    assert "DB_NAME ?= ke_engine" in content
    assert "DB_USER ?= ke_engine" in content
    assert "docker compose up -d postgres" in content
    assert "docker compose exec postgres pg_isready -U $(DB_USER) -d postgres" in content
    assert "DROP DATABASE IF EXISTS $(DB_NAME) WITH (FORCE)" in content
    assert "CREATE DATABASE $(DB_NAME) OWNER $(DB_USER)" in content
    assert "cd $(BACKEND_DIR) && $(UV) run alembic upgrade head" in content
