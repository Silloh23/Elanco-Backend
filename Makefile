.PHONY: run test lint ingest demo-quarantine
run:
	uv run python -m tickwatch

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy src

ingest:
	uv run python -m tickwatch.ingest

demo-quarantine:
	uv run python scripts/demo_quarantine.py
