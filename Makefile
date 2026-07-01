BACKEND_DIR ?= backend
UV ?= uv

API_HOST ?= 127.0.0.1
API_PORT ?= 8000

CELERY_APP ?= app.infrastructure.celery:celery_app
CELERY_LOG_LEVEL ?= info
ifeq ($(OS),Windows_NT)
CELERY_POOL ?= solo
else
CELERY_POOL ?= prefork
endif

.DEFAULT_GOAL := help

.PHONY: help backend-sync dev dev-api dev-worker dev-infra dev-all-infra test-backend

help:
	@echo "Available targets:"
	@echo "  make backend-sync     Sync backend dependencies with uv"
	@echo "  make dev-infra        Start lightweight backend infra: postgres redis minio"
	@echo "  make dev-all-infra    Start all docker compose services"
	@echo "  make dev-api          Start FastAPI backend on API_HOST/API_PORT"
	@echo "  make dev-worker       Start Celery document conversion worker"
	@echo "  make dev              Start API and worker in parallel"
	@echo "  make test-backend     Run backend pytest suite"

backend-sync:
	cd $(BACKEND_DIR) && $(UV) sync

dev-infra:
	docker compose up -d postgres redis minio

dev-all-infra:
	docker compose up -d

dev-api:
	cd $(BACKEND_DIR) && $(UV) run uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

dev-worker:
	cd $(BACKEND_DIR) && $(UV) run celery -A $(CELERY_APP) worker -l $(CELERY_LOG_LEVEL) -P $(CELERY_POOL)

dev:
	$(MAKE) -j 2 dev-api dev-worker

test-backend:
	cd $(BACKEND_DIR) && $(UV) run python -m pytest
