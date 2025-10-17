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
- **Restart**: After code changes, restart backend with `docker restart kbxy-backend`

## Database Schema & Models

### Core Models (`server/app/models.py`)

#### Monster Model
- **Primary Key**: `id` (auto-increment)
- **Unique Constraint**: `name` field - **IMPORTANT**: Name must be unique across all monsters
- **Key Fields**:
  - `name`: Unique monster name (String, indexed)
  - `element`: Element type (String, indexed, nullable)
  - `possess`: Boolean flag for owned status
  - `type`: Acquisition channel/type (String, indexed, nullable)
  - `method`: Acquisition method description (Text, nullable)
  - Stats: `hp`, `speed`, `attack`, `defense`, `magic`, `resist` (Float)
  - `all_forms`: JSON list of all form names (UTF8JSON)
- **Relationships**:
  - `tags`: Many-to-many with Tag (via `monster_tag` table)
  - `monster_skills`: One-to-many with MonsterSkill (association object)
  - `collection_links`: One-to-many with CollectionItem
  - `skills`: Association proxy to Skill objects via monster_skills
  - `collections`: Association proxy to Collection objects via collection_links

#### Skill Model
- **Unique Constraint**: Composite key on (`name`, `element`, `kind`, `power`, `pp`)
- **Key Fields**:
  - `name`: Skill name (String, indexed)
  - `element`, `kind`, `power`, `pp`: Skill attributes
  - `description`: Skill description (Text)
- **Relationships**:
  - `monster_skills`: One-to-many with MonsterSkill
  - `monsters`: Association proxy via monster_skills

#### MonsterSkill (Association Object)
- **Purpose**: Many-to-many relationship between Monster and Skill with extra data
- **Unique Constraint**: Composite key on (`monster_id`, `skill_id`)
- **Key Fields**:
  - `selected`: Boolean flag for recommended/selected skills
- **Pattern**: Association object pattern - allows storing relationship-level attributes

#### Tag Model
- **Unique Constraint**: `name` field
- **Relationships**: Many-to-many with Monster (via `monster_tag` table)

#### Collection & CollectionItem
- **Collection**: User-defined monster collections/folders
  - Unique constraint on `name`
  - `color`: Optional color tag (String)
  - `items_count`: Cached count of items
- **CollectionItem**: Association object for Collection-Monster relationship
  - Composite primary key: (`collection_id`, `monster_id`)

### Custom Types
- **UTF8JSON**: Custom TypeDecorator for JSON fields with proper Chinese character support
  - Stores as Text in SQLite
  - Uses `ensure_ascii=False` for proper encoding

## Business Logic & Services

### Tags System (`server/app/services/tags_service.py`)
Complex tag recognition and classification system with multiple strategies:

#### Tag Recognition Strategies
1. **Regex-based** (`suggest_tags_grouped`): Pattern matching using `config/tags_catalog.json`
2. **AI-based** (`ai_suggest_tags_grouped`): DeepSeek API for intelligent classification
3. **Hybrid** (`repair_union`): Combines regex + AI with verification

#### Configuration
- `TAG_WRITE_STRATEGY`: Choose `"ai"`, `"regex"`, or `"repair_union"`
- `TAG_USE_SELECTED_ONLY`: Only analyze skills marked as `selected=True`
- `TAG_AI_REPAIR_VERIFY`: Verify AI suggestions with keyword matching
- `TAGS_CATALOG_PATH`: Path to tag definitions JSON
- `DEEPSEEK_API_KEY`: API key for AI tagging
- `DEEPSEEK_MAX_CONCURRENT`: Concurrent AI requests (default: 3)

#### Tag Categories
- **buff**: Self/ally beneficial effects (attack↑, heal, shield, etc.)
- **debuff**: Enemy debuffs (attack↓, stun, poison, etc.)
- **special**: Special mechanics (multi-hit, first strike, PP drain, etc.)

#### Batch Processing
- `start_ai_batch_tagging()`: Background thread for bulk AI tagging
- `get_ai_batch_progress()`: Track progress with job_id
- `cancel_ai_batch()`: Cancel running batch job
- Uses asyncio + httpx for concurrent API calls

### Monster Service (`server/app/services/monsters_service.py`)
- `list_monsters()`: Complex filtering with tags, elements, collection_id, need_fix
- `upsert_tags()`: Atomic tag creation/lookup

### Skills Service (`server/app/services/skills_service.py`)
- `upsert_skills()`: Upsert skills by composite unique key

### Collection Service (`server/app/services/collection_service.py`)
- Collection management with monster relationships

### Combat Service (`server/app/services/combat_service.py`)
- `CombatAnalyzer.calculate_combat_tendencies()`: Calculates attack/defense tendency scores

### Crawler Service (`server/app/services/crawler_service.py`)
- Web scraping for monster data (65KB file - complex crawling logic)

### Image Service (`server/app/services/image_service.py`)
- Image URL resolution by monster name matching
- Serves from `data/images/monsters/` (configurable via `KBXY_IMAGES_DIR`)

## API Patterns & Conventions

### Error Handling
- **400 Bad Request**: Client errors with descriptive Chinese messages
  - Example: Duplicate monster name returns "妖怪名字 'xxx' 已存在（ID: xxx），请使用其他名字"
- **404 Not Found**: Resource not found
- **500 Internal Server Error**: Should be avoided - validate inputs first

### Validation Rules
- **Monster Creation/Update**: Check name uniqueness BEFORE database commit
- **Skills**: Upsert by composite unique key to avoid duplicates
- **Tags**: Upsert by name to avoid duplicates

### Response Patterns
- List endpoints: Return `{items: [], total: int, has_more: bool, etag: str}`
- Detail endpoints: Return full object with relationships pre-loaded
- Mutation endpoints: Return updated object or `{ok: true, ...}`

### Database Session Management
- Use `selectinload()` for eager loading relationships
- Commit after validation, not before
- Rollback on errors in batch operations

## Common Development Tasks

### Adding New Tag Recognition Pattern
1. Edit `server/app/services/config/tags_catalog.json`
2. Add pattern under `patterns.{buff|debuff|special}.{tag_code}`
3. Use `{ENEMY}`, `{ONE_OR_TWO}` macros from `fragments` section
4. Reload is automatic (TTL-based cache)

### Modifying Database Schema
1. Update models in `server/app/models.py`
2. Schema auto-init in dev mode (main.py)
3. For production: Manual migration (no Alembic configured)

### Testing API Changes
- Dev: `make server` (auto-reload enabled)
- Docker: `docker restart kbxy-backend` after code changes

### Debugging Docker Issues
```bash
docker logs kbxy-backend --tail 100  # View backend logs
docker logs kbxy-frontend --tail 100 # View frontend logs
docker exec -it kbxy-backend /bin/bash  # Enter backend container
```

## Important Constraints & Rules

### Database Constraints
1. **Monster.name**: UNIQUE - Always check before insert/update
2. **Skill**: UNIQUE on (name, element, kind, power, pp)
3. **Tag.name**: UNIQUE - Use upsert pattern
4. **MonsterSkill**: UNIQUE on (monster_id, skill_id)
5. **CollectionItem**: Composite PRIMARY KEY on (collection_id, monster_id)

### Cascade Behavior
- Deleting Monster: Cascades to monster_skills, monster_tag, collection_items
- Deleting Collection: Cascades to collection_items
- Deleting Skill: Cascades to monster_skills

### SQLite Specifics
- WAL mode enabled for better concurrency
- Timeout settings: `SQLITE_BUSY_TIMEOUT_MS` (default 4000ms)
- No foreign key enforcement by default (check constraints manually)

## Testing & Verification

### Health Check
```bash
curl http://localhost:8000/health
# Returns: version, monster count, tag count, etc.
```

### API Testing
- Swagger UI: http://localhost:8000/docs (FastAPI auto-generated)
- ReDoc: http://localhost:8000/redoc

## Project-Specific Patterns

### Association Object Pattern
Used for many-to-many relationships that need extra fields:
- `MonsterSkill`: Adds `selected` flag to Monster-Skill relationship
- `CollectionItem`: Could add ordering, notes, etc. to Collection-Monster relationship

### Service Layer Pattern
- Routes are thin - delegate to service functions
- Services contain business logic and database operations
- Services can be reused across multiple routes

### Upsert Pattern
Commonly used for tags and skills to avoid duplicate entries:
```python
# Example pattern - find existing records, create missing ones
def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    existing = db.query(Tag).filter(Tag.name.in_(names)).all()
    existing_names = {t.name for t in existing}
    new_tags = [Tag(name=n) for n in names if n not in existing_names]
    db.add_all(new_tags)
    db.flush()
    return existing + new_tags
```