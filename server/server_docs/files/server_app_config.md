---
file: server/app/config.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: []
exposes: [Settings, settings]
---

## TL;DR（30 秒）
- **职责**：集中管理基础配置（应用名、运行环境、SQLite 绝对路径解析、CORS 白名单、SQLite `busy_timeout`/连接超时默认值）。
- **实现**：Pydantic `BaseModel` + 环境变量 `APP_ENV/KBXY_DB_PATH/SQLITE_BUSY_TIMEOUT_MS/SQLITE_CONNECT_TIMEOUT_S`，统一将 DB 文件解析到**项目根**`/data/` 下（绝对路径）。
- **默认值**  
  - `APP_ENV=dev`（仅支持 `dev/test`，其他值回落 `dev`）  
  - `KBXY_DB_PATH` 未设置时：`dev→data/kbxy-dev.db`，`test→data/kbxy-test.db`  
  - `SQLITE_BUSY_TIMEOUT_MS=4000`（4s）、`SQLITE_CONNECT_TIMEOUT_S=5`（5s）  
  - `cors_origins=["http://localhost:5173","http://127.0.0.1:5173"]`
- **常见坑**
  1. 设了 **`KBXY_DB_PATH` 为固定文件名/路径** → `dev/test` 会**共用同一库文件**（有意或无意，请确认）。  
  2. 若设置了 **`DATABASE_URL`**，`db.py` 会**优先用它**并在启动日志提示“本地路径被忽略”。  
  3. “项目根”通过 `Path(__file__).resolve().parents[2]` 推导，**不是 CWD**；相对路径会被拼到 `<project>/data/`。  
  4. `cors_origins` 目前**不支持**环境变量覆盖（如需，见“变更指南”）。

---

## 职责与边界
- **做什么**：提供类型化配置与**本地 SQLite 绝对路径**解析；给 `db.py/main.py` 使用；提供默认的 SQLite 超时参数。  
- **不做什么**：不负责决定最终连接来源优先级（该逻辑在 `db.py`：`DATABASE_URL > 本地文件`）；不做 .env 解析（由运行环境或 Uvicorn `--env-file` 完成）。

---

## 公开接口
- `class Settings(BaseModel)` 字段：
  - `app_name: str`  
  - `app_env: str`（仅 `dev/test`，其他值回落 `dev`）  
  - `cors_origins: list[str]`  
  - `kbxy_db_path: str | None`（可为相对/绝对/仅文件名）  
  - `sqlite_busy_timeout_ms: int`（写锁等待，毫秒）  
  - `sqlite_connect_timeout_s: float`（连接打开等待，秒）
- 方法：
  - `normalized_env() -> str`：返回 `dev` 或 `test`  
  - `default_db_filename() -> str`：按环境返回默认文件名  
  - `resolved_local_db_path() -> Path`：返回**最终绝对路径**（优先 `KBXY_DB_PATH`，否则 `<project>/data/<env 默认名>`）
- 单例：`settings: Settings`

---

## 依赖与数据流
- **上游输入**（环境变量）：`APP_ENV`、`KBXY_DB_PATH`、`SQLITE_BUSY_TIMEOUT_MS`、`SQLITE_CONNECT_TIMEOUT_S`  
- **下游使用**：  
  - `db.py`：构建 SQLAlchemy Engine、在 `connect` 事件里设置 `PRAGMA busy_timeout` 并打印启动信息。  
  - `main.py`：启动日志打印环境信息、路径三件套等。

> 启动日志（由 `db.py` 输出）将包含：  
> `DB absolute path / Parent dir / Writable / Busy timeout (ms) / Connect timeout (s)`。

---

## 输入 / 输出
**输入**  
- `APP_ENV`：`dev` 或 `test`  
- `KBXY_DB_PATH`：可为绝对/相对路径或仅文件名（相对与文件名都会拼到 `<project>/data/`）  
- `SQLITE_BUSY_TIMEOUT_MS`（默认 4000）  
- `SQLITE_CONNECT_TIMEOUT_S`（默认 5）

**输出（常用取值）**  
- `settings.app_env`（标准化前的原值）  
- `settings.sqlite_busy_timeout_ms` / `settings.sqlite_connect_timeout_s`  
- `settings.resolved_local_db_path()` → `Path('/abs/.../project/data/kbxy-*.db')`

---

## 错误与可观测性
- **错误征兆**：  
  - `writable=FAIL`（父目录不可写）；  
  - dev/test 误共用库（设置了统一 `KBXY_DB_PATH` but 预期隔离）；  
  - 线上日志显示“DB in use: DATABASE_URL (...) ignored local file”，但你却期望本地文件生效。  
- **排查**：  
  - 看启动日志的路径与超时参数；  
  - 确认 `.env.<env>` 是否设置了 `DATABASE_URL`/`KBXY_DB_PATH`；  
  - 打印 `settings.resolved_local_db_path()` 验证最终路径。

---

## 示例
```py
from server.app.config import settings

print("env(normalized) =", settings.normalized_env())
print("db path =", settings.resolved_local_db_path())
print("busy(ms) =", settings.sqlite_busy_timeout_ms, "connect(s) =", settings.sqlite_connect_timeout_s)
```

```bash
# 使用 .env.test 启动（Uvicorn 会加载其中的 APP_ENV/KBXY_DB_PATH 等）
uvicorn server.app.main:app --env-file .env.test

# 临时指定 busy_timeout = 5000ms（测试环境）
SQLITE_BUSY_TIMEOUT_MS=5000 APP_ENV=test uvicorn server.app.main:app
```

---

## 变更指南（How to change safely）
- **新增配置项**：在 `Settings` 增加字段与默认值，并在使用点容错（避免破坏旧行为）。  
- **让 `cors_origins` 支持环境覆盖**：  
  - 轻量方案：读取 `os.getenv("CORS_ORIGINS")`，按逗号拆分并 strip。  
  - 规范方案：引入 `pydantic-settings`（`BaseSettings`）统一 .env/环境变量优先级。  
- **扩展环境类型**：若未来需要 `prod/staging`，请同步更新 `normalized_env()` 的校验与默认文件映射。

---

## 自测清单
- [ ] 未设置任何变量启动，日志显示 `APP_ENV=dev`，DB 解析到 `<project>/data/kbxy-dev.db`。  
- [ ] `APP_ENV=test` 启动，DB 解析为 `<project>/data/kbxy-test.db`。  
- [ ] 设 `KBXY_DB_PATH="kbxy.db"`，两环境解析到同一 `<project>/data/kbxy.db`（符合预期）。  
- [ ] 设 `SQLITE_BUSY_TIMEOUT_MS=5000`，启动日志出现 `Busy timeout (ms): 5000`。  
- [ ] 设 `DATABASE_URL=...`，启动日志出现“`DB in use: DATABASE_URL (local file ignored)`”。

---

## 术语与约定
- **项目根**：`Path(__file__).resolve().parents[2]`  
- **路径拼接**：相对/仅文件名一律拼在 `<project>/data/` 并返回**绝对路径**  
- **连接优先级**：`DATABASE_URL > 本地文件（resolved_local_db_path）`（在 `db.py` 执行）