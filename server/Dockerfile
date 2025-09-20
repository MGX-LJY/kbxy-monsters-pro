# server/Dockerfile
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    APP_ENV=dev \
    KBXY_DB_PATH=/app/data/kbxy-dev.db

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# 复制server代码
COPY . /app/

# 复制初始化脚本和数据 
COPY init-data.sh /app/init-data.sh
RUN chmod +x /app/init-data.sh

EXPOSE 8000

# 启动脚本：先初始化数据，再启动应用
CMD ["sh", "-c", "/app/init-data.sh && uvicorn app.main:app --host 0.0.0.0 --port 8000"]