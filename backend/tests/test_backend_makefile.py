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
    assert "CELERY_POOL" not in content
    assert "celery -A" not in content
