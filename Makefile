.PHONY: dev up down logs test lint web-build migrate

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api web simulator thingsboard

test:
	uv run pytest --cov=apps/api/arthra --cov-report=term-missing

lint:
	uv run ruff check apps services tests
	pnpm --dir apps/web lint

web-build:
	pnpm --dir apps/web build

migrate:
	uv run alembic -c apps/api/alembic.ini upgrade head

