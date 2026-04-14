.PHONY: help install up down migrate test lint fmt typecheck clean reindex-tsv dump-feeds

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-20s %s\n", $$1, $$2}'

install: ## install dev dependencies
	pip install -e ".[dev]"

up: ## start dev stack
	docker compose up -d

down: ## stop dev stack
	docker compose down

migrate: ## apply migrations
	python manage.py migrate

test: ## run pytest
	pytest -q

lint: ## ruff + black --check + isort --check
	ruff check src tests
	black --check src tests
	isort --check-only src tests

fmt: ## format with black + isort
	isort src tests
	black src tests

typecheck: ## mypy
	mypy src

clean: ## drop caches
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov build dist *.egg-info
