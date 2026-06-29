# Backend And Frontend Split Design

## Goal

Split the repository into separate `backend/` and `frontend/` areas while preserving the existing FastAPI backend behavior.

## Architecture

The FastAPI project becomes a self-contained backend subproject under `backend/`. Its `pyproject.toml`, `app/`, and `tests/` move together so backend commands can run from `backend/` without depending on root-level Python packaging.

The `frontend/` directory is created as a neutral placeholder because no frontend framework has been specified. It contains a README instead of generated React, Vue, or other framework files.

## Verification

Backend tests run from `backend/` using the local virtual environment. A project-layout test asserts that `backend/app/main.py`, `backend/pyproject.toml`, `backend/tests`, and `frontend/README.md` exist.

