---
file: server/app/db.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/config.py, SQLAlchemy]
exposes: [DATABASE_URL, engine, SessionLocal, Base]
---

# db.py · 快速卡片

## TL;DR（30 秒）
- **职责**：集中创建 SQLAlchemy `engine`、`SessionLocal` 和 `Base`，并为 SQLite 设置关键 PRAGMA。
- **存储**：SQLite（pysqlite 驱动），数据库路径来自 `settings.db_path` → 组装为 `sqlite+pysqlite:///{path}`。
- **SQLite 优化**：连接时设置 `journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`。
- **常见坑**
  1. **相对路径**导致 DB 落盘位置不一致（取决于进程工作目录）。
  2. 并发写入仍可能触发 `database is locked`（可考虑 `busy_timeout`；见“变更指南”）。
  3. 当前文件**未读取 `DATABASE_URL` 环境变量**，只使用 `settings.db_path`。

## 职责与边界
- **做什么**：初始化 Engine/Session/Base；为每个新连接配置 SQLite PRAGMA。
- **不做什么**：不做模型建表（`Base.metadata.create_all` 应在应用启动处执行）；不做迁移与种子数据。

## 公开接口
- `DATABASE_URL: str` —— 形如 `sqlite+pysqlite:///kbxy-dev.db`。
- `engine` —— `create_engine(..., future=True, connect_args={"check_same_thread": False})`
- `SessionLocal` —— `sessionmaker(autoflush=False, autocommit=False, future=True)`
- `Base` —— `declarative_base()`，供模型继承。

## 依赖与数据流
- **上游输入**：`settings.db_path`（由 `config.py` 提供）。
- **下游使用者**：`models.py`（继承 `Base`）、`services/*` 与 `routes/*`（请求级打开会话）。
- **连接生命周期**：每个 DB 连接 `connect` 事件时执行一次 PRAGMA；对所有连接生效。

## SQLite 配置（PRAGMA）
- `journal_mode=WAL`：提高并发读写能力，生成 `*.db-wal/*.db-shm` 文件（**勿手删**）。
- `synchronous=NORMAL`：在 WAL 下的推荐取值，减少 fsync 次数，性能与可靠性折中。
- `foreign_keys=ON`：开启外键约束（SQLite 默认关闭）。

## 会话与线程
- `check_same_thread=False`：允许跨线程使用同一连接对象（FastAPI/uvicorn 场景常用）。
- `SessionLocal`：**非自动提交/刷新**；需显式 `commit()`/`rollback()`/`close()`。
- **推荐依赖（FastAPI）**：
```py
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

## 错误与可观测性
- **锁冲突**：`sqlite3.OperationalError: database is locked`  
  - 缓解：WAL 已开启；仍可考虑 `PRAGMA busy_timeout`、减小长事务、避免大批量写入与读竞争。
- **外键失败**：`sqlite3.IntegrityError: FOREIGN KEY constraint failed`（已启用外键约束）。
- **调试日志**：将 `create_engine(..., echo=True)` 暂时开启以追踪 SQL。

## 示例（最常用 1–2 个）
```py
# 定义模型
from sqlalchemy import Column, Integer, String
from server.app.db import Base

class Demo(Base):
    __tablename__ = "demo"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
```

```py
# 应用启动时一次性建表（如在 main.py 中）
from server.app.db import Base, engine
Base.metadata.create_all(bind=engine)
```

## 变更指南（How to change safely）
- **支持 `DATABASE_URL` 优先级**（推荐）  
  将 `DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+pysqlite:///{settings.db_path}"`，对接未来的 Postgres 等。
- **降低锁冲突**  
  在 `connect` 事件中追加：`PRAGMA busy_timeout=3000;`（毫秒）；对大量写入接口，拆分批次并缩短事务。
- **可观测性增强**  
  - 增加启动日志打印 `engine.url` 与 `journal_mode`（查询 `PRAGMA journal_mode;`）。
  - 为关键写入点打点并关联 `x-trace-id`。
- **测试可注入**  
  - 将 Engine/Session 封装为 `get_engine(url=...)` 与 `get_session(bind)`，测试时传入临时文件或内存库（`sqlite+pysqlite:///:memory:`）。
- **迁移到 Postgres（未来）**  
  - 替换驱动与 URL；删除 SQLite 特有 PRAGMA；配置连接池/超时；引入 Alembic 迁移。

## 自测清单
- [ ] 默认配置可启动，`Base.metadata.create_all()` 正常建表。
- [ ] 显式设置 `KBXY_DB_PATH="$(pwd)/kbxy-dev.db"` 后，DB 实际落在项目根目录。
- [ ] 高并发 GET 与适度 POST 场景下无频繁 `database is locked`。
- [ ] 外键约束可被触发并按预期报错。
- [ ] 打开 `echo=True` 时能看到完整 SQL 输出（调试后关闭）。