# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Backend (FastAPI)
```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt

# Run server (development mode with auto-reload)
make server                    # Default: APP_ENV=test
make server APP_ENV=dev        # Dev environment
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

### Database & Seeding
```bash
make seed       # Run seed script (python scripts/seed.py)
```

## Architecture Overview

### Tech Stack
- **Backend**: FastAPI + SQLAlchemy 2.x + SQLite with WAL mode
- **Frontend**: React + TypeScript + Vite + Tailwind CSS (local build)
- **Data**: SQLite database with configurable environments (dev/test)

### Key Components

#### Backend Structure (`server/app/`)
- `main.py` - FastAPI app with CORS, middleware, and route registration
- `config.py` - Environment-based settings with `APP_ENV` support (dev/test)
- `db.py` - SQLAlchemy setup with SQLite connection management
- `models.py` - Database models
- `schemas.py` - Pydantic schemas for API validation
- `routes/` - API endpoints organized by feature
- `services/` - Business logic layer

#### Frontend Structure (`client/`)
- Built with Vite + React + TypeScript
- Uses React Query for state management
- React Hook Form + Zod for form validation
- Tailwind CSS for styling (locally built, not CDN)

#### Database Configuration
- Environment controlled via `APP_ENV` environment variable
- Default files: `kbxy-dev.db` (dev), `kbxy-test.db` (test)
- Override with `KBXY_DB_PATH` environment variable
- SQLite timeout settings configurable via environment variables

### Key Features
- Monster data management with CSV import/export
- Rating and tagging system with rule engine
- Search and filtering capabilities
- Health check endpoints
- Import preview/commit workflow

### Environment Variables
- `APP_ENV`: dev/test (defaults to dev)
- `KBXY_DB_PATH`: Override default database file path
- `SQLITE_BUSY_TIMEOUT_MS`: SQLite busy timeout (default: 4000ms)
- `SQLITE_CONNECT_TIMEOUT_S`: Connection timeout (default: 5s)

### Development Notes
- Backend runs on port 8000, frontend on port 5173
- CORS configured for localhost development
- Auto-reload enabled for server development
- Use UTF-8 encoding for CSV imports
- Project designed for local single-machine use