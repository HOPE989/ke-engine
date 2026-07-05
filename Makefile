BACKEND_DIR ?= backend
UV ?= uv
DB_NAME ?= ke_engine
DB_USER ?= ke_engine

API_HOST ?= 127.0.0.1
API_PORT ?= 8000

.DEFAULT_GOAL := help

.PHONY: help backend-sync dev dev-api dev-worker dev-infra dev-all-infra db-init kafka-topics-init kafka-topics-list test-backend

help:
	@echo "Available targets:"
	@echo "  make backend-sync     Sync backend dependencies with uv"
	@echo "  make dev-infra        Start lightweight backend infra: postgres redis minio kafka"
	@echo "  make dev-all-infra    Start all docker compose services"
	@echo "  make db-init          Reset local database and upgrade schema to head"
	@echo "  make kafka-topics-init Create local Kafka topics"
	@echo "  make kafka-topics-list List local Kafka topics"
	@echo "  make dev-api          Start FastAPI backend on API_HOST/API_PORT"
	@echo "  make dev-worker       Start Kafka document conversion worker"
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

dev-api:
	cd $(BACKEND_DIR) && $(UV) run uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

dev-worker:
	cd $(BACKEND_DIR) && $(UV) run python -m app.workers.kafka_worker

dev:
	$(MAKE) -j 2 dev-api dev-worker

test-backend:
	cd $(BACKEND_DIR) && $(UV) run python -m pytest
