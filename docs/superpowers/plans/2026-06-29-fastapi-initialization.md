# FastAPI Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal, runnable FastAPI application using the requested layered `app/` structure.

**Architecture:** `app.main:create_app()` constructs the FastAPI app, registers core cross-cutting behavior, and mounts `/api/v1`. Feature modules expose routers and keep schemas, models, services, repositories, and exceptions close to their domain. Async SQLAlchemy is configured against the existing Postgres compose service.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy async, pytest, httpx.

---

## File Structure

- Create `pyproject.toml` for package metadata, runtime dependencies, pytest config, and import path setup.
- Create `app/main.py` for ASGI app construction and health check.
- Create `app/core/config.py`, `security.py`, `logging.py`, and `exceptions.py` for settings, security helpers, logging, and error handlers.
- Create `app/db/base.py`, `session.py`, and `migrations/.gitkeep` for database primitives.
- Create `app/api/deps.py` and `app/api/v1/router.py` for shared dependencies and versioned routing.
- Create `app/modules/users/*`, `app/modules/auth/*`, and `app/modules/orders/*` for initial domain boundaries.
- Create `app/common/pagination.py`, `response.py`, and `enums.py` for shared DTOs and enum types.
- Create `tests/conftest.py`, `tests/test_main.py`, and `tests/test_security.py` for initial behavior coverage.

### Task 1: Failing Tests And Dependency Config

**Files:**
- Create: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/test_main.py`
- Create: `tests/test_security.py`

- [ ] **Step 1: Write the failing tests**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ke-engine"}


def test_api_v1_module_routes_are_mounted():
    client = TestClient(app)

    assert client.get("/api/v1/users/").status_code == 200
    assert client.get("/api/v1/auth/health").status_code == 200
    assert client.get("/api/v1/orders/").status_code == 200
```

```python
from app.core.security import get_password_hash, verify_password


def test_password_hash_verifies_plain_password():
    hashed = get_password_hash("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q`

Expected: FAIL because `app.main` and `app.core.security` do not exist yet.

### Task 2: Core Application Skeleton

**Files:**
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/core/logging.py`
- Create: `app/core/exceptions.py`
- Create: `app/core/security.py`
- Create: `app/common/__init__.py`
- Create: `app/common/response.py`
- Create: `app/common/pagination.py`
- Create: `app/common/enums.py`

- [ ] **Step 1: Implement minimal app and shared primitives**

Create the FastAPI app factory, settings, logging, exception handlers, password hashing helpers, and shared response models.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_security.py -q`

Expected: PASS after security helpers are implemented.

### Task 3: Database And Module Routes

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/db/migrations/.gitkeep`
- Create: `app/api/__init__.py`
- Create: `app/api/deps.py`
- Create: `app/api/v1/__init__.py`
- Create: `app/api/v1/router.py`
- Create: `app/modules/__init__.py`
- Create files under `app/modules/users/`, `app/modules/auth/`, and `app/modules/orders/`

- [ ] **Step 1: Implement routers and module scaffolding**

Create versioned API routing and placeholder module endpoints that return valid JSON responses.

- [ ] **Step 2: Run all tests**

Run: `python -m pytest -q`

Expected: PASS with health, route mounting, and security tests green.

### Task 4: Runtime Verification

**Files:**
- No source edits unless verification exposes a defect.

- [ ] **Step 1: Verify ASGI app import**

Run: `python -c "from app.main import app; print(app.title)"`

Expected: prints `ke-engine`.

- [ ] **Step 2: Start development server when dependencies are installed**

Run: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

Expected: Uvicorn starts and serves `/health`.

