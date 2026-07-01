from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    raise AssertionError("Could not locate repository root")


def test_project_is_split_into_backend_and_frontend():
    root = _repo_root()

    assert (root / "backend" / "app" / "main.py").is_file()
    assert (root / "backend" / "pyproject.toml").is_file()
    assert (root / "backend" / "tests").is_dir()
    assert (root / "frontend" / "README.md").is_file()


def test_placeholder_modules_do_not_carry_unused_service_repository_model_scaffolding():
    root = _repo_root()
    forbidden_files = [
        root / "backend" / "app" / "modules" / "auth" / "schemas.py",
        root / "backend" / "app" / "modules" / "auth" / "security.py",
        root / "backend" / "app" / "modules" / "auth" / "service.py",
        root / "backend" / "app" / "modules" / "users" / "exceptions.py",
        root / "backend" / "app" / "modules" / "users" / "models.py",
        root / "backend" / "app" / "modules" / "users" / "repository.py",
        root / "backend" / "app" / "modules" / "users" / "service.py",
        root / "backend" / "app" / "modules" / "orders" / "models.py",
        root / "backend" / "app" / "modules" / "orders" / "repository.py",
        root / "backend" / "app" / "modules" / "orders" / "service.py",
    ]

    existing_forbidden_files = [
        str(path.relative_to(root)) for path in forbidden_files if path.exists()
    ]

    assert existing_forbidden_files == []

