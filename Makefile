COMPOSE ?= docker compose
# --build: the tools image picks up dependency changes before every run.
DEV := $(COMPOSE) run --rm --build dev

.PHONY: help up down logs ps migrate superuser shell test cov lint fmt typecheck check pre-commit \
	reindex-tsv dump-feeds db-reset

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-14s %s\n", $$1, $$2}'

up: ## build and start the stack (api, worker, beat, db, redis, mailpit)
	$(COMPOSE) up -d --build

down: ## stop the stack
	$(COMPOSE) down

logs: ## follow logs of app services
	$(COMPOSE) logs -f api worker beat

ps: ## show service status
	$(COMPOSE) ps

migrate: ## apply migrations
	$(COMPOSE) run --rm migrate

superuser: ## create a staff account (manages feeds, tags and tag rules)
	$(COMPOSE) run --rm api python manage.py createsuperuser

shell: ## Django shell inside the api image
	$(COMPOSE) run --rm api python manage.py shell

test: ## run pytest in the dev container
	$(DEV) pytest

cov: ## run pytest with coverage
	$(DEV) pytest --cov --cov-report=term-missing

lint: ## ruff lint + format check
	$(DEV) sh -c "ruff check . && ruff format --check ."

fmt: ## apply ruff fixes and formatting
	$(DEV) sh -c "ruff check --fix . && ruff format ."

typecheck: ## mypy (strict)
	$(DEV) mypy src

check: lint typecheck test ## lint, typecheck and test

pre-commit: ## run all pre-commit hooks on the whole tree
	$(DEV) sh -c "git config --global --add safe.directory /app && pre-commit run --all-files"

reindex-tsv: ## rebuild articles_article.tsv through the trigger
	$(COMPOSE) run --rm api python manage.py shell -c "from django.db import connection; connection.cursor().execute('UPDATE articles_article SET title = title')"

dump-feeds: ## dump feeds to initial_feeds.json (git-ignored)
	$(COMPOSE) run --rm -T api python manage.py dumpdata feeds.feed --indent 2 > initial_feeds.json

db-reset: ## drop the dev database volume and recreate it (DESTRUCTIVE)
	$(COMPOSE) down -v
	$(COMPOSE) up -d db
