from pathlib import Path


def test_root_makefile_exposes_backend_dev_targets():
    makefile = Path(__file__).resolve().parents[2] / "Makefile"

    content = makefile.read_text(encoding="utf-8")

    assert "dev-api:" in content
    assert "dev-worker:" in content
    assert "dev-infra:" in content
    assert "$(UV) run uvicorn app.main:app --reload" in content
    assert "$(UV) run celery -A $(CELERY_APP) worker -l" in content
