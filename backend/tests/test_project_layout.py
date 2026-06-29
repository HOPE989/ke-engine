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

