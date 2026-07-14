BACKEND_DIR ?= backend
UV ?= uv
DB_NAME ?= ke_engine
DB_USER ?= ke_engine

API_HOST ?= 127.0.0.1
DOCUMENT_API_PORT ?= 8000
CHAT_API_PORT ?= 8001
CELERY_BEAT_SCHEDULE ?= .runtime/celerybeat-schedule

.DEFAULT_GOAL := help

.PHONY: help backend-sync dev dev-document-api dev-chat-api dev-worker dev-celery-worker dev-celery-beat dev-infra dev-all-infra db-init kafka-topics-init kafka-topics-list test-backend

help:
	@echo "Available targets:"
	@echo "  make backend-sync     Sync backend dependencies with uv"
	@echo "  make dev-infra        Start lightweight backend infra: postgres redis minio kafka"
	@echo "  make dev-all-infra    Start all docker compose services"
	@echo "  make db-init          Reset local database and upgrade schema to head"
	@echo "  make kafka-topics-init Create local Kafka topics"
	@echo "  make kafka-topics-list List local Kafka topics"
	@echo "  make dev-document-api Start Document API on API_HOST/DOCUMENT_API_PORT"
	@echo "  make dev-chat-api     Start Chat API on API_HOST/CHAT_API_PORT"
	@echo "  make dev-worker       Start Kafka document conversion worker"
	@echo "  make dev-celery-worker Start Celery worker for scheduled compensation tasks"
	@echo "  make dev-celery-beat  Start Celery beat scheduler"
	@echo "  make dev              Start API and worker in parallel"
	@echo "  make test-backend     Run backend pytest suite"

backend-sync:
	cd $(BACKEND_DIR) && $(UV) sync

dev-infra:
	docker compose up -d postgres redis minio kafka

dev-all-infra:
	docker compose up -d

db-init:
	docker compose up -d postgres
	docker compose exec postgres pg_isready -U $(DB_USER) -d postgres
	docker compose exec postgres psql -U $(DB_USER) -d postgres -c "DROP DATABASE IF EXISTS $(DB_NAME) WITH (FORCE);"
	docker compose exec postgres psql -U $(DB_USER) -d postgres -c "CREATE DATABASE $(DB_NAME) OWNER $(DB_USER);"
	cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

kafka-topics-init:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic document.convert.requested --partitions 1 --replication-factor 1
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic document.embed_store.requested --partitions 1 --replication-factor 1

kafka-topics-list:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --list

dev-document-api:
	cd $(BACKEND_DIR) && $(UV) run uvicorn app.entrypoints.document_api:app --reload --host $(API_HOST) --port $(DOCUMENT_API_PORT)

dev-chat-api:
	cd $(BACKEND_DIR) && $(UV) run uvicorn app.entrypoints.chat_api:app --reload --host $(API_HOST) --port $(CHAT_API_PORT)

dev-worker:
	cd $(BACKEND_DIR) && $(UV) run python -m app.entrypoints.document_worker

dev-celery-worker:
	cd $(BACKEND_DIR) && $(UV) run celery -A app.entrypoints.celery_worker.celery_app worker -l INFO --pool=solo

dev-celery-beat:
	cd $(BACKEND_DIR) && $(UV) run python -c "from pathlib import Path; Path('$(CELERY_BEAT_SCHEDULE)').parent.mkdir(parents=True, exist_ok=True)"
	cd $(BACKEND_DIR) && $(UV) run celery -A app.entrypoints.celery_worker.celery_app beat -l INFO --schedule $(CELERY_BEAT_SCHEDULE)

dev:
	$(MAKE) -j 2 dev-document-api dev-worker

test-backend:
	cd $(BACKEND_DIR) && $(UV) run python -m pytest
