.PHONY: help install up down migrate test lint fmt typecheck clean reindex-tsv dump-feeds db-reset

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

reindex-tsv: ## force re-build of articles_article.tsv via no-op UPDATE
	python manage.py shell -c "from django.db import connection; cur=connection.cursor(); cur.execute('UPDATE articles_article SET title = title;')"

dump-feeds: ## dump active feeds as json fixture
	python manage.py dumpdata feeds.feed --indent 2 -o initial_feeds.json

db-reset: ## drop and recreate dev db (DESTRUCTIVE)
	docker compose stop db
	docker compose rm -fv db
	docker volume rm newsforge_db_data || true
	docker compose up -d db
