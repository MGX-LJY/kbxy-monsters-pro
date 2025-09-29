# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Backend (FastAPI)
```bash
# 注意：所有 make 命令必须在项目根目录执行

# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt

# Run server (development mode with auto-reload)
make server                    # Default: APP_ENV=dev
uvicorn server.app.main:app --reload --port 8000  # Direct command
```

### Frontend (React + Vite)
```bash
# Install dependencies
cd client && npm i

# Run development server
make client
cd client && npm run dev       # Direct command (http://localhost:5173)

# Build for production
cd client && npm run build
```

### Combined Development
```bash
make install    # Install both backend and frontend dependencies
make dev        # Instructions to run both servers
```

### Docker Deployment
```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker logs kbxy-backend
docker logs kbxy-frontend

# Stop services
docker-compose down

# Backend runs on port 8000, frontend on port 8080 (Nginx)
# Data persisted in ./docker-data directory
```

## Architecture Overview

### Tech Stack
- **Backend**: FastAPI + SQLAlchemy 2.x + SQLite with WAL mode
- **Frontend**: React + TypeScript + Vite + Tailwind CSS (local build)
- **Data**: SQLite database
- **Deployment**: Docker (production environment)

### Key Components

#### Backend Structure (`server/app/`)
- `main.py` - FastAPI app with CORS, middleware, route registration, and schema auto-init (dev only)
- `config.py` - Environment-based settings with `APP_ENV` support (dev/prod)
- `db.py` - SQLAlchemy setup with SQLite WAL mode and connection pooling
- `models.py` - Database models (Monster, Skill, Tag, etc.)
- `schemas.py` - Pydantic v2 schemas for API validation
- `routes/` - API endpoints organized by feature (monsters, skills, crawl, warehouse, collections, etc.)
- `services/` - Business logic layer (import_service, rules_engine, rating calculations)

#### Frontend Structure (`client/`)
- Built with Vite + React + TypeScript
- Uses React Query for state management
- React Hook Form + Zod for form validation
- Tailwind CSS for styling (locally built, not CDN)

#### Database Configuration
- Environment controlled via `APP_ENV` environment variable: `dev` (local development) or `prod` (docker production)
- Default database file: `kbxy-dev.db` (located in `data/` directory)
- Override with `KBXY_DB_PATH` environment variable
- SQLite timeout settings configurable via environment variables

### Key Features
- Monster data management with CSV import/export
- Rating and tagging system with rule engine
- Search and filtering capabilities
- Health check endpoints
- Import preview/commit workflow

### Environment Variables
- `APP_ENV`: dev (local development) or prod (docker production), defaults to dev
- `KBXY_DB_PATH`: Override default database file path
- `SQLITE_BUSY_TIMEOUT_MS`: SQLite busy timeout (default: 4000ms)
- `SQLITE_CONNECT_TIMEOUT_S`: Connection timeout (default: 5s)
- `TAG_USE_SELECTED_ONLY`: Use only selected skills for tag recognition (default: true)

### Development Notes
- Backend runs on port 8000, frontend on port 5173 (dev) or 8080 (docker)
- CORS configured for localhost development
- Auto-reload enabled for server development
- Use UTF-8 encoding for CSV imports
- Schema auto-initialization only runs in dev environment (not prod)
- SQLite uses WAL mode for better concurrency
- Static image files served from `data/images/monsters/` (configurable via `KBXY_IMAGES_DIR`)
- Project designed for local single-machine use

### Docker Architecture
- **Backend**: Python 3.11-slim with uvicorn, exposes port 8000
- **Frontend**: Node 18 build stage + Nginx alpine runtime, exposes port 80
- **Data Persistence**: `./docker-data` directory mounted to `/app/data` in backend container
- **Networking**: Services communicate via `kbxy-network` (default bridge)
- **Healthcheck**: Backend health endpoint (`/health`) checked every 30s