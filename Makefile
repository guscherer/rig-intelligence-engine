.RECIPEPREFIX = >

PY := uv run
SRC := src

.PHONY: help install check lint format type arch test test-live size clean up down ingest ingest-smoke ingest-full embed search eval-retrieval run

help:
> @echo "install  - cria venv e instala deps (dev)"
> @echo "check    - roda TODO o gate do CI (é o que o CI roda)"
> @echo "lint     - ruff check"
> @echo "format   - ruff format + fix"
> @echo "type     - mypy --strict"
> @echo "arch     - import-linter (fronteiras de pacote)"
> @echo "size     - relatório de LOC por módulo (warning, não falha)"
> @echo "test     - pytest sem testes live"
> @echo "up/down  - docker compose postgres + redis"

install:
> uv sync --extra dev --extra embed

check: lint format-check type arch test
> @echo "OK - gate completo passou"

lint:
> $(PY) ruff check .

format-check:
> $(PY) ruff format --check .

format:
> $(PY) ruff check --fix .
> $(PY) ruff format .

type:
> $(PY) mypy

arch:
> $(PY) lint-imports --no-logo

size:
> $(PY) python scripts/size_report.py

test:
> $(PY) pytest -m "not live"

test-live:
> $(PY) pytest -m live

ingest-smoke:
> $(PY) pytest -m integration tests/integration/test_ingest_e2e.py -q

ingest:
> $(PY) python scripts/ingest.py

ingest-full: ingest

embed:
> $(PY) python scripts/embed.py

search:
> $(PY) python scripts/search.py $(filter-out $@,$(MAKECMDGOALS))

run:
> $(PY) python scripts/run.py $(filter-out $@,$(MAKECMDGOALS))

eval-retrieval:
> $(PY) python scripts/eval_retrieval.py

up:
> docker compose up -d
> docker compose ps

down:
> docker compose down

clean:
> rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov

%:
> @:
