下面是**更新后的《kbxy-monsters-pro · 后端开发文档（Standalone）》**，已把你当前仓库结构、爬虫/技能规范化、仓库接口、备份/恢复、常见坑（PYTHONPATH、DB 路径、唯一键冲突、/api/v1 与 / 的路由差异）等都补齐。直接保存为：`docs/kbxy-backend-dev-guide.md` 覆盖即可。

---

# kbxy-monsters-pro · 后端开发文档（Standalone）

> 面向后端开发与联调：架构、环境、数据模型、接口、导入策略（幂等 + 单事务）、爬虫、备份/恢复、批量操作、错误约定与自测。  
> **更新日期**：2025-08-15

---

## 1) 概览

- **技术栈**：FastAPI · Pydantic v2 · SQLAlchemy 2.x · SQLite（WAL）
- **运行方式**：本地单机；默认 DB 文件放在**项目根目录** `kbxy-dev.db`
- **核心能力**
  - 妖怪数据 CRUD、检索、排序、分页、标签聚合
  - CSV/TSV **导入预览** + **单事务提交** + **Idempotency-Key 幂等**
  - 规则引擎产出 `explain_json`（含 `raw_stats` 六维 & 自动标签）
  - **备份/恢复**（JSON）与**导出**（CSV）
  - **技能管理**（名称去重 + 规范化存储）
  - **4399 图鉴爬虫**：单页抓取 / 全站遍历；自动识别六维、元素、获取渠道；**技能元素/类型规范化**
  - 仓库（possess）批量增删、以及“可获取（new_type）”标记

---

## 2) 目录结构（后端相关）

```
server/
  app/
    __init__.py
    main.py               # 应用入口（CORS、TraceID、路由、统一异常）
    config.py             # 配置（应用名、CORS、DB 路径、环境变量）
    db.py                 # SQLAlchemy Engine/Session，SQLite PRAGMA（WAL）
    middleware.py         # TraceID 中间件（x-trace-id）
    models.py             # Monster / Skill / Tag / ImportJob / Task
    schemas.py            # Pydantic v2 请求/响应模型
    routes/
      health.py
      monsters.py         # 列表/详情/CRUD/批删
      skills.py           # GET/PUT /monsters/{id}/skills
      skills_admin.py     # （可选）技能清理/维护
      importing.py        # 导入预览/提交（幂等 + 单事务）
      tags.py             # 标签聚合
      recalc.py           # 重算示例
      backup.py           # 统计、导出 CSV、备份/恢复
      warehouse.py        # 仓库清单 + 批量 possess 设定
      derive.py           # 派生/建议（单个与批量）
      tasks.py            # 异步任务（可选）
      crawl.py            # 4399 图鉴爬虫（fetch_one / crawl_all）
    services/
      rules_engine.py
      monsters_service.py
      skills_service.py
      import_service.py
      derive_service.py
      crawler_server.py   # 4399 爬虫实现（BS4 + DrissionPage）
```

> ⚠️ 你的仓库中**根目录**与 `server/` 下都各有一套 `kbxy-dev.db{,-wal,-shm}`。**请统一只用根目录这套**（见“配置/环境变量”）。

---

## 3) 启动与环境

### 3.1 快速开始

```bash
# 进入仓库根目录
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt

# 最简单启动（开发）
PYTHONPATH="$(pwd)" \
KBXY_DB_PATH="$(pwd)/kbxy-dev.db" \
uvicorn server.app.main:app --reload --host 0.0.0.0 --port 8000
```

或使用仓库脚本（**后台**拉起前后端）：

```bash
# 后台启动脚本
./start-bg.sh
# 停止
./stop-bg.sh
```

> 如需显式指定 DB 路径与 PYTHONPATH：
>
> ```bash
> ROOT="$(pwd)" \
> PYTHONPATH="$ROOT" \
> KBXY_DB_PATH="$ROOT/kbxy-dev.db" \
> ./start-bg.sh
> ```

### 3.2 配置 / 环境变量

- `KBXY_DB_PATH`（推荐）：SQLite 文件路径（默认：项目根目录 `kbxy-dev.db`）
- `DATABASE_URL`：完整 SQLAlchemy URL（如 `sqlite:////absolute/path/to/kbxy-dev.db`）  
  > 指定了 `DATABASE_URL` 会**优先生效**；否则退回 `KBXY_DB_PATH`。
- `CORS_ORIGINS`：逗号分隔，默认允许 `http://localhost:5173`、`http://127.0.0.1:5173`
- 运行时必须保证 `PYTHONPATH` 指向项目根，这样 `uvicorn server.app.main:app` 才找得到 `server` 包。

### 3.3 SQLite PRAGMA（见 `db.py`）

- `journal_mode=WAL`、`synchronous=NORMAL`、`foreign_keys=ON`  
  产生 `kbxy-dev.db-wal` / `kbxy-dev.db-shm` 文件，属正常现象。

---

## 4) 数据模型（要点）

- **Monster**
  - `id (PK)`、`name (unique)`、`element?`、`role?`
  - `possess (bool)`、`new_type (bool)`、`type?/method?`（**获取渠道/方式**）
  - 六维：`hp/speed/attack/defense/magic/resist`（均 `REAL` 存储）
  - `explain_json (json)`：包含 `raw_stats` 与规则解释
  - 关系：`tags (m2m Tag)`、`skills (m2m Skill)`
  - `created_at/updated_at`
- **Skill**
  - `id (PK)`、`name (idx)`、`element?/kind?/power?/description?`
  - element/kind 在爬虫与保存层均做**规范化**（详见 §6）
- **Tag**：`name (unique)`；与 Monster 多对多
- **ImportJob / Task**：导入幂等/异步任务记录

> **唯一约束**：`monsters.name` 唯一。重名创建将报 409（或 500/IntegrityError，视你本地是否已合并“友好捕获”的改动）。

---

## 5) 接口一览

### 5.1 健康检查

- **GET** `/health` → `200 OK`

### 5.2 列表/详情/CRUD

- **GET** `/monsters`
  - Query：`q?`（名称/技能关键字）、`element?`、`role?`
  - 获取途径：`type?`/`acq_type?`/`acquire_type?`/`type_contains?`
  - “仅可获取”：`new_type=true|false`
  - 标签：`tag?`（单）或 `tags_all?=buf_x&tags_all=deb_y`（多 AND）
  - 排序：`sort? = updated_at|name|offense|survive|control|tempo|pp_pressure`（默认 `updated_at`）  
    `order? = asc|desc`（默认 `desc`）
  - 分页：`page`（默认 1）、`page_size`（默认 20，最大 200）
- **GET** `/monsters/{id}`
- **POST** `/monsters`（创建）
  - **重名** → 若后端已合并友好处理，将返回 `409 Conflict` + `detail="名称已存在（id=...）"`  
    否则会抛 `sqlite3.IntegrityError`
- **PUT** `/monsters/{id}`（更新）
- **DELETE** `/monsters/{id}`
- **DELETE|POST** `/monsters/bulk_delete`（Body：`{ "ids": [1,2,3] }`）

### 5.3 技能（按怪物）

- **GET** `/monsters/{id}/skills`  
  → `[{ id, name, element?, kind?, power?, description? }]`
- **PUT** `/monsters/{id}/skills`
  - **Body**：**裸数组**（推荐）
    ```json
    [
      {"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"有10%机会窒息"},
      {"name":"明王咒","element":"特殊","kind":"特殊","power":null,"description":"本回合不动，下回合伤害加倍"}
    ]
    ```
  - 行为：覆盖绑定集合（内部 upsert + 去重，名称为主）

### 5.4 标签聚合

- **GET** `/tags?with_counts=true` → `[{ name, count }]`  
  （前端仅展示 `buf_* / deb_* / util_*` 三类）

### 5.5 统计/导出/备份/恢复（`backup.py`）

- **GET** `/stats` → `{ total, with_skills, tags_total }`
- **GET** `/export/monsters.csv`（尊重筛选）
- **GET** `/backup/export_json`（含怪物/标签/技能 + 六维在 `explain_json.raw_stats`）
- **POST** `/backup/restore_json`
  - 按 `name` + `element?` 做 upsert；覆盖标签与技能；回写 `raw_stats`

### 5.6 仓库（possess）

- **GET** `/warehouse`
  - Query 与 `/monsters` 一致；分页/排序同理
- **POST** `/warehouse/bulk_set`  
  Body：`{ "ids": [1,2,3], "possess": true }`

### 5.7 派生 / 建议

- **GET** `/monsters/{id}/derived`  
  → `{ role_suggested?: string, tags?: string[] }`
- **POST** `/derived/batch` 或 **POST** `/api/v1/derived/batch`（兼容两路由）  
  Body：`{ "ids": [ ... ] }`（缺省=对符合当前筛选的全量做）

### 5.8 爬虫（4399 图鉴）

- **POST** `/api/v1/crawl/fetch_one`  
  ```json
  {"url":"https://news.4399.com/kabuxiyou/yaoguaidaquan/shuixi/201201-21-139866.html"}
  ```
  **响应示例**：
  ```json
  {
    "name": "碧青水龙兽",
    "element": "水系",
    "hp": 98, "speed": 96, "attack": 87, "defense": 81, "magic": 113, "resist": 85,
    "type": "活动获取宠物",
    "new_type": false,
    "method": "获取方式：完成 ...",
    "selected_skills": [
      {"name":"明王咒","element":"特殊","kind":"特殊","power":0,"description":"...","level":27},
      {"name":"水浪拍击","element":"水系","kind":"物理","power":95,"description":"...","level":41},
      {"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"...","level":60}
    ]
  }
  ```
  > **字段规范化**：技能 `element` 会把 `"特"|"无"` 统一为 `"特殊"`；`kind` 会把 `"技能"| "特" | "状态"|...` 统一到 `"法术"` 或 `"特殊"`（参见 `services/crawler_server.py` 中 `normalize_skill_element/kind`）。
- **GET** `/api/v1/crawl/fetch_one?url=...`（同上）
- **POST** `/api/v1/crawl/crawl_all`  
  Body（可选）：`{"limit": 100}`  
  → 遍历站内列表页，逐条抓取，返回 `{seen, fetched, inserted, updated, skills_changed}`

---

## 6) 技能字段规范化（重要）

- **element（技能属性）**
  - `"特"|"无"` → `"特殊"`；单字元素如 `"水"` → `"水系"`（前端展示时 `"特殊"` 不当做元素）
- **kind（技能类型）**
  - `"技能"|"技"` → `"法术"`
  - `"状态"|"变化"|"辅助"|"特"` → `"特殊"`
- **power**
  - 无/非数 → `null`；`0` 保留为 `0`（例如纯状态技）
- **description**
  - 去空白、去噪（零宽/全角空格等）

> 爬虫与 `PUT /monsters/{id}/skills` 都遵循此规范，确保统计与去重稳定。

---

## 7) 导入（预览 & 提交）

### 7.1 预览

- **POST** `/import/preview`（`multipart/form-data`，字段名 `file`）
- 自动识别分隔符（`,` / `\t` / `;` / `|`）与常见表头别名（中文/英文）

### 7.2 提交（单事务 + 幂等）

- **POST** `/import/commit`（同上）
- 可选请求头：`Idempotency-Key: <string>`（相同 Key 的重复提交直接返回上次结果）
- 行为：
  - 单事务；任一错误整体回滚
  - upsert 依据：`name` + `element?`
  - 写入 `explain_json.raw_stats={hp,speed,attack,defense,magic,resist,sum}`
  - 标签合并：规则引擎 + 技能文本派生 + CSV 标签
  - 技能：名称去重 + upsert 绑定

---

## 8) 错误与 Trace

- 响应头：`x-trace-id`
- 典型错误：
  - **409 Conflict**：创建时 `name` 重复（或返回 500/IntegrityError，视版本）
  - **404 Not Found**：请求了不存在的带前缀路由（如 `/api/v1/monsters`）；当前版本**有效路由为** `/monsters`
- 通用错误体：
  ```json
  {
    "type":"about:blank","title":"Validation Error","status":422,
    "code":"VALIDATION_ERROR","detail":"...","trace_id":"..."
  }
  ```

---

## 9) 自测清单（curl）

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 列表（分页）
curl "http://127.0.0.1:8000/monsters?sort=updated_at&order=desc&page=1&page_size=20"

# 技能（读取/覆盖）
curl "http://127.0.0.1:8000/monsters/1/skills"
curl -X PUT -H "Content-Type: application/json" \
  -d '[{"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"..."}]' \
  http://127.0.0.1:8000/monsters/1/skills

# 标签聚合
curl "http://127.0.0.1:8000/tags?with_counts=true"

# 备份/导出/恢复
curl -OJ "http://127.0.0.1:8000/export/monsters.csv"
curl -OJ "http://127.0.0.1:8000/backup/export_json"
curl -X POST -H "Content-Type: application/json" -d @backup.json \
  http://127.0.0.1:8000/backup/restore_json

# 批删
curl -X DELETE -H "Content-Type: application/json" \
  -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/monsters/bulk_delete

# 仓库批量
curl -X POST -H "Content-Type: application/json" \
  -d '{"ids":[10,11], "possess": true}' http://127.0.0.1:8000/warehouse/bulk_set

# 派生（单个/批量）
curl "http://127.0.0.1:8000/monsters/1/derived"
curl -X POST -H "Content-Type: application/json" \
  -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/derived/batch

# 爬虫（单页）
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"url":"https://news.4399.com/kabuxiyou/yaoguaidaquan/shuixi/201201-21-139866.html"}' \
  http://127.0.0.1:8000/api/v1/crawl/fetch_one | jq

# 爬虫（全站）
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"limit": 50}' http://127.0.0.1:8000/api/v1/crawl/crawl_all | jq
```

---

## 10) 常见问题（Troubleshooting）

### Q1. `ModuleNotFoundError: No module named 'server'`
- 原因：`uvicorn` 启动时 `PYTHONPATH` 没指到项目根。
- 解决：
  ```bash
  PYTHONPATH="$(pwd)" uvicorn server.app.main:app --reload
  ```
  或在 `start-bg.sh` 中导出：
  ```bash
  export PYTHONPATH="${PYTHONPATH:-$ROOT}"
  ```

### Q2. “为什么没用我的本地数据库？”
- 统一用**根目录**的 `kbxy-dev.db`。请确保：
  - 环境变量：
    ```bash
    KBXY_DB_PATH="$(pwd)/kbxy-dev.db"
    # 或
    DATABASE_URL="sqlite:///$PWD/kbxy-dev.db"
    ```
  - `server/` 子目录下那份 DB 常是旧缓存，可删除或忽略，避免误用。

### Q3. 创建时报 `sqlite3.IntegrityError: UNIQUE constraint failed: monsters.name`
- 你在 `POST /monsters` 时使用了**已存在的 name**。
- 处理方式：
  1) **推荐**：改走 `PUT /monsters/{id}` 更新；  
  2) 或让后端在 `create` 里捕获 `IntegrityError` → 返回 `409 Conflict`；  
  3) 若真要覆盖，请先删除旧记录或改名。

### Q4. 前端打到 `/api/v1/monsters` 404？
- 当前版本只挂了 `/monsters` 路由；`/api/v1/monsters` 是历史兜底写法。  
  统一把前端 API 指向 `/monsters`（或在后端加一个 alias）。

### Q5. SQLite 出现 `*.db-wal/*.db-shm`？
- 因为 WAL 模式。**不要手工删**；正常随进程维护。

---

## 11) 版本与约定

- OpenAPI 自动生成；新增字段请先灰度
- 技能元素/类型**必须遵循**本文件的规范化映射
- 需要切换数据库（Postgres 等），请更新 `DATABASE_URL` 与索引策略

---

**附：爬虫规范化映射（节选，自 `services/crawler_server.py`）**

- `element`：`"特"|"无"` → `"特殊"`；其它如 `"水"` → `"水系"`
- `kind`：`"技能"|"技"` → `"法术"`；`"状态"|"变化"|"辅助"|"特"` → `"特殊"`

--- 

> 如需把“创建重名 → 409”合并到你本地，请在 `server/app/routes/monsters.py` 的 `create` 中捕获 `IntegrityError` 并返回 409（此前在联调答复里给过示例代码）。