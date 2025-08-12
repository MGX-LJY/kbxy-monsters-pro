SHELL := /bin/bash

.PHONY: install dev server client seed

install:
	python3 -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt
	cd client && npm i

server:
	uvicorn server.app.main:app --reload --port 8000

client:
	cd client && npm run dev

dev:
	@echo "Open two terminals: `make server` and `make client`"

seed:
	python scripts/seed.py
