from pathlib import Path


def test_root_makefile_exposes_backend_dev_targets():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "dev-document-api:" in content
    assert "dev-agent-api:" not in content
    assert "dev-worker:" in content
    assert "dev-infra:" in content
    assert "$(UV) run uvicorn app.entrypoints.document_api:app --reload" in content
    assert "app.entrypoints.agent_api:app" not in content
    assert "app.main:app" not in content
    assert "dev-api:" not in content
    assert "DOCUMENT_API_PORT ?= 8000" in content
    assert "CHAT_API_PORT ?= 8001" in content
    assert "AGENT_API_PORT" not in content
    assert "$(MAKE) -j 2 dev-document-api dev-worker" in content
    assert "$(UV) run python -m app.entrypoints.document_worker" in content
    assert "docker compose up -d postgres redis minio kafka" in content
    assert "kafka-topics-init:" in content
    assert "kafka-topics-list:" in content
    assert "kafka-topics.sh" in content
    assert "--create" in content
    assert "--if-not-exists" in content
    assert "--topic document.convert.requested" in content
    assert "--topic document.embed_store.requested" in content


def test_root_makefile_exposes_chat_api_target():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "dev-chat-api:" in content
    assert "make dev-chat-api" in content
    assert (
        "$(UV) run uvicorn app.entrypoints.chat_api:app --reload "
        "--host $(API_HOST) --port $(CHAT_API_PORT)"
    ) in content


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


def test_root_makefile_exposes_celery_compensation_targets():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "CELERY_BEAT_SCHEDULE ?= .runtime/celerybeat-schedule" in content
    assert "dev-celery-worker:" in content
    assert "dev-celery-beat:" in content
    assert "celery -A app.entrypoints.celery_worker.celery_app worker -l INFO --pool=solo" in content
    assert "mkdir -p" not in content
    assert (
        "Path('$(CELERY_BEAT_SCHEDULE)').parent.mkdir(parents=True, exist_ok=True)"
    ) in content
    assert (
        "celery -A app.entrypoints.celery_worker.celery_app beat -l INFO "
        "--schedule $(CELERY_BEAT_SCHEDULE)"
    ) in content


def test_root_gitignore_excludes_celery_runtime_state():
    gitignore = Path(__file__).resolve().parents[2] / ".gitignore"

    content = gitignore.read_text(encoding="utf-8")

    assert "backend/.runtime/" in content
    assert "backend/celerybeat-schedule*" in content
