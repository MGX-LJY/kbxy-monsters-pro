SHELL := /bin/bash

.PHONY: install dev server client

# 默认环境：dev（本地开发），生产环境使用 docker
export APP_ENV ?= dev

install:
	python3 -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt
	cd client && npm i

server:
	@echo "Starting server with APP_ENV=$(APP_ENV)"
	uvicorn server.app.main:app --reload --port 8000 \
	  --reload-dir server \
	  --reload-exclude '.venv/*' \
	  --reload-exclude '*/site-packages/*' \
	  --reload-exclude '**/__pycache__/*'

client:
	cd client && npm run dev

dev:
	@echo "Open two terminals: \`make server\` and \`make client\`"
