---
file: server/app/db.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/config.py, SQLAlchemy]
exposes: [engine, SessionLocal, Base, startup_db_report_lines]
---

## TL;DR（30 秒）
- **职责**：集中创建 SQLAlchemy `engine`、`SessionLocal` 与 `Base`，并在连接建立时设置 SQLite 关键 `PRAGMA`。  
- **存储选择优先级**：`DATABASE_URL` > 本地 SQLite 文件（由 `settings.resolved_local_db_path()` 解析到 `<project>/data/…` 的**绝对路径**）。  
- **连接与并发**：`check_same_thread=False`，连接打开超时 `timeout = settings.sqlite_connect_timeout_s`（秒）；每个连接设置 `PRAGMA busy_timeout = settings.sqlite_busy_timeout_ms`（毫秒）以缓解写锁冲突。  
- **启动可观测性**：提供 `startup_db_report_lines()`；日志包含：DB 绝对路径、父目录、可写性、`busy_timeout(ms)`、`connect_timeout(s)`、以及「是否使用了 `DATABASE_URL`」。  

---

## 职责与边界
- **做什么**  
  - 解析最终数据库连接（环境变量优先）。  
  - 创建 Engine / Session / Base。  
  - 在 `connect` 事件中为新连接设置：`journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`、`busy_timeout=<ms>`。  
  - 汇总并输出启动时的 DB 信息（供 `main.py` 在 `startup` 钩子里打印）。  
- **不做什么**  
  - 不做模型迁移（后续由 Alembic 接管）。  
  - 不在模块顶层建表（避免 `--reload` 时的并发竞态；建表应在 `main.py` 的受控启动流程里执行）。

---

## 公开接口
- `engine: sqlalchemy.Engine` —— 已带 `check_same_thread=False` 与 `timeout=<connect_timeout_s>`。  
- `SessionLocal: sessionmaker` —— `autoflush=False`、`autocommit=False`、`future=True`。  
- `Base: DeclarativeMeta` —— 供模型继承。  
- `startup_db_report_lines() -> list[str]` —— 返回用于启动日志的多行状态文本（路径/权限/超时等）。  

> 说明：内部还有 `DB_INFO`（启动信息缓存）与 `FINAL_DATABASE_URL`（最终连接串）等内部字段，默认不直接对外使用。

---

## 连接与 PRAGMA（SQLite）
- `journal_mode=WAL`：提高并发读写能力（会生成 `*.db-wal`/`*.db-shm`）。  
- `synchronous=NORMAL`：在 WAL 场景的推荐值，可靠性/性能折中。  
- `foreign_keys=ON`：开启外键约束。  
- `busy_timeout = settings.sqlite_busy_timeout_ms`（默认 4000ms，可通过环境变量调至 3000–5000ms）。  
- `timeout = settings.sqlite_connect_timeout_s`（默认 5s，控制**打开连接**时等待锁的时间）。  

---

## 存储路径与优先级
1. 若设置 **`DATABASE_URL`**：直接使用该连接串（并在启动日志标注“使用 DATABASE_URL，本地文件被忽略”）。  
2. 否则使用本地 SQLite：`settings.resolved_local_db_path()` → `<project>/data/<env 默认名或 KBXY_DB_PATH>`；启动时会**确保父目录存在**并检查可写性。  

---

## 常见坑 & 提示
- `busy_timeout` 不是“银弹”：它能显著降低并发写入的锁冲突，但仍应避免**长事务/大批量单事务**、减少“读-写”竞争。  
- 若设置了 `KBXY_DB_PATH` 为统一文件名，`dev/test` 将共用同一 DB；如需隔离，请删除该变量或分别指定。  
- 使用 `uvicorn --reload` 时，**不要**在模块顶层调用 `Base.metadata.create_all()`；应在 `main.py` 的 `startup` 中加锁/受控执行（你已按此实践改造）。  

---

## 示例
```py
# main.py（片段）：启动时打印 DB 状态
from server.app.db import engine, Base, startup_db_report_lines

@app.on_event("startup")
async def _startup_logs():
    for line in startup_db_report_lines():
        logger.info(f"[startup] {line}")
    # 如需初始化 schema，请在此执行受控 create_all（避免 reload 竞态）
    # Base.metadata.create_all(bind=engine, checkfirst=True)
```

```py
# 依赖注入（FastAPI）
from contextlib import contextmanager
from server.app.db import SessionLocal

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

---

## 自测清单
- [ ] 未设置 `DATABASE_URL`，日志显示本地 SQLite 的**绝对路径**、父目录、`Writable=OK`、并打印 `Busy timeout` 与 `Connect timeout`。  
- [ ] 设置 `DATABASE_URL=...` 启动，日志出现 “DB in use: DATABASE_URL (local file ignored)”。  
- [ ] 将 `SQLITE_BUSY_TIMEOUT_MS` 分别设为 `0 / 5000` 跑 `scripts/sqlite_stress_write.py`，验证 `locked` 明显下降。  
- [ ] `uvicorn --reload` 多进程下无“重复建索引/表”的报错（建表逻辑在受控的 `startup` 中）。  

---

## 变更指南（How to change safely）
- **切换外部数据库**：设置 `DATABASE_URL`（如 Postgres/MySQL），并在 `connect` 事件中移除 SQLite 特有 `PRAGMA`。  
- **调整并发策略**：可通过环境变量微调 `SQLITE_BUSY_TIMEOUT_MS` 与 `SQLITE_CONNECT_TIMEOUT_S`；如并发继续提升，考虑迁移到 PG/MySQL 并配合连接池/隔离级别。  
- **可观测性增强**：需要时可在 `startup_db_report_lines()` 中补充 `engine.url`（脱敏）或读取 `PRAGMA journal_mode` 的回读值用于日志核对。