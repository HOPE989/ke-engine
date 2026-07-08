from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    raise AssertionError("Could not locate repository root")


def test_project_is_split_into_backend_and_frontend():
    root = _repo_root()

    assert not (root / "backend" / "app" / "main.py").exists()
    assert (root / "backend" / "app" / "entrypoints" / "document_api.py").is_file()
    assert (root / "backend" / "app" / "entrypoints" / "agent_api.py").is_file()
    assert (root / "backend" / "app" / "services" / "document_api").is_dir()
    assert (root / "backend" / "app" / "services" / "agent_api").is_dir()
    assert (root / "backend" / "app" / "domains" / "document").is_dir()
    assert (root / "backend" / "app" / "domains" / "agent").is_dir()
    assert (root / "backend" / "pyproject.toml").is_file()
    assert (root / "backend" / "tests").is_dir()
    assert (root / "frontend" / "README.md").is_file()


def test_placeholder_modules_do_not_carry_unused_service_repository_model_scaffolding():
    root = _repo_root()
    assert not (root / "backend" / "app" / "modules").exists()

