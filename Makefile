# FenJue Engine — Makefile
# ==========================

.PHONY: install run docker docker-down docker-logs clean

install:
	pip install -r requirements.txt

run:
	uvicorn api.app:app --host 0.0.0.0 --port 8001 --reload

docker:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
