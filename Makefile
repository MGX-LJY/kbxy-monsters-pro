SHELL := /bin/bash

.PHONY: install dev server client seed

# 默认环境：dev；可通过 `make server APP_ENV=test` 覆盖
export APP_ENV ?= test

install:
	python3 -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt
	cd client && npm i

server:
	@echo "APP_ENV=$(APP_ENV)"
	uvicorn server.app.main:app --reload --port 8000 \
	  --reload-dir server --reload-dir rules \
	  --reload-exclude '.venv/*' \
	  --reload-exclude '*/site-packages/*' \
	  --reload-exclude '**/__pycache__/*'

client:
	cd client && npm run dev

dev:
	@echo "Open two terminals: \`make server\` and \`make client\`"

seed:
	python scripts/seed.py