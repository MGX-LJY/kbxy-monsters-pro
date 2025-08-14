# server/Dockerfile
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# 如果你用 apt 依赖（psycopg 等），在这里加
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# 依赖 —— 任选其一：
# 1) requirements.txt（推荐简单）
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# 2) 如果你用 poetry：
# COPY pyproject.toml poetry.lock* /app/
# RUN pip install --upgrade pip poetry && poetry install --no-root --no-interaction

# 复制代码
COPY . /app

EXPOSE 8000

# 如果入口是 app/main.py 里有 FastAPI 实例 app，则这样启动：
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000"]