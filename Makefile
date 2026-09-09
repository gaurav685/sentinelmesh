# SentinelMesh developer tasks.
#
# Windows note: `make` is not installed by default. Every target is a single
# command line — run it directly, or use WSL/Git Bash with `make`. The exact
# commands are also listed in deploy/docker/README.md.

PY ?= python
COMPOSE ?= docker compose -f deploy/docker/docker-compose.yml

.PHONY: help setup lint fmt typecheck test test-unit test-integration contracts \
        up down logs migrate provision-topics topics psql redis run clean

help:
	@echo "setup            install all packages editable into the active venv"
	@echo "lint / fmt       ruff check / ruff check --fix"
	@echo "typecheck        mypy --strict over every package src tree"
	@echo "test             full suite (integration tests skip without Docker)"
	@echo "test-unit        skip integration tests"
	@echo "test-integration only integration tests (needs 'make up')"
	@echo "contracts        regenerate JSON Schema from sm_contracts"
	@echo "up / down        start / stop the local stack (postgres, redis, migrate, app)"
	@echo "migrate          alembic upgrade head against the local database"
	@echo "run              run api-gateway on the host"

setup:
	$(PY) -m pip install -e "packages/contracts-py[dev]" -e "packages/common-py[dev]" -e "services/api-gateway[dev]" -e "services/ingestion-gateway[dev]" -e "services/normalization-engine[dev]"

lint:
	$(PY) -m ruff check packages services tests migrations scripts

fmt:
	$(PY) -m ruff check --fix packages services tests migrations scripts

typecheck:
	$(PY) -m mypy --strict --python-version 3.11 \
		packages/contracts-py/src/sm_contracts \
		packages/common-py/src/sm_common \
		services/api-gateway/src/sm_api_gateway \
		services/ingestion-gateway/src/sm_ingestion_gateway \
		services/normalization-engine/src/sm_normalization_engine

test:
	$(PY) -m pytest packages services tests -q

test-unit:
	$(PY) -m pytest packages services tests -q -m "not integration"

test-integration:
	$(PY) -m pytest tests/integration -q -m integration

contracts:
	$(PY) scripts/gen_contracts.py
	$(PY) scripts/gen_contracts.py --check

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f app migrate

migrate:
	$(PY) -m alembic -c migrations/postgres/alembic.ini upgrade head

provision-topics:
	$(PY) scripts/provision_topics.py

topics:
	$(PY) scripts/provision_topics.py --list

psql:
	$(COMPOSE) exec postgres psql -U $${SM_PG_USER:-sentinelmesh} -d $${SM_PG_DB:-sentinelmesh}

redis:
	$(COMPOSE) exec redis redis-cli

run:
	$(PY) -m sm_api_gateway

clean:
	$(PY) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
