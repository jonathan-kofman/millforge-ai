.PHONY: help install dev-backend dev-frontend test lint build docker-up docker-down

help:
	@echo "MillForge – available commands:"
	@echo "  make install        Install all dependencies"
	@echo "  make dev-backend    Run FastAPI backend with hot-reload"
	@echo "  make dev-frontend   Run Vite React frontend"
	@echo "  make test           Run all pytest tests"
	@echo "  make test-v         Run tests with verbose output"
	@echo "  make lint           Lint backend with ruff (install separately)"
	@echo "  make docker-up      Start full stack with Docker Compose"
	@echo "  make docker-down    Stop Docker Compose stack"

install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

dev-backend:
	cd backend && uvicorn main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest ../tests/ -v

test-v:
	cd backend && python -m pytest ../tests/ -v --tb=short

lint:
	cd backend && ruff check .

build:
	cd frontend && npm run build

docker-up:
	docker compose up --build

docker-down:
	docker compose down
