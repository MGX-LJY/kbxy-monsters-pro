# kbxy-monsters-pro · 后端开发文档（Standalone）

> 目标：为**后端开发与联调**提供一份可直接落地的说明书；涵盖架构、环境、数据模型、接口规范、导入策略（幂等 + 单事务）、异步任务、错误约定与自测指引。

---

## 1. 概览

- **技术栈**：FastAPI · Pydantic v2 · SQLAlchemy 2.x · SQLite（WAL 模式）  
- **运行方式**：本地单机；默认 DB 文件 `kbxy-dev.db` 存放于项目根目录。  
- **主要能力**
  - 妖怪数据 CRUD、检索、排序、分页；
  - CSV/TSV **导入预览** + **单事务提交** + **幂等 Idempotency-Key**；
  - 规则引擎输出 `explain_json`（可解释性）；
  - **同步/异步**重算（/recalc 与 /tasks/*）；
  - Trace-ID 贯通与结构化错误体。

---

## 2. 目录结构（后端）

```
server/
  app/
    __init__.py
    main.py               # 应用入口（CORS、TraceID、中间件、路由、错误处理）
    config.py             # 环境配置（应用名、DB 路径、CORS）
    db.py                 # SQLAlchemy Engine/Session，SQLite PRAGMA
    models.py             # Monster/Tag/ImportJob/Task 等模型
    schemas.py            # Pydantic 请求/响应模型
    middleware.py         # TraceID 中间件（x-trace-id 响应头）
    routes/
      health.py
      monsters.py
      importing.py
      recalc.py
      tags.py
      tasks.py
    services/
      rules_engine.py     # 打分与标签示例
      monsters_service.py # 列表查询、标签 upsert、解释计算
      import_service.py   # 预览/提交、幂等与事务
server/requirements.txt
rules/default_rules.json
scripts/seed.py
```

---

## 3. 快速开始

```bash
# 进入仓库根目录
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
uvicorn server.app.main:app --reload --port 8000

# 浏览 API 文档（FastAPI 自动生成）
# http://127.0.0.1:8000/docs
# OpenAPI JSON: http://127.0.0.1:8000/openapi.json
```

**环境变量**
- `KBXY_DB_PATH`：自定义 SQLite 文件路径（默认 `kbxy-dev.db`）。

**CORS**
- 允许来源（默认）：`http://localhost:5173`, `http://127.0.0.1:5173`。按需在 `server/app/config.py` 修改。

---

## 4. 数据模型（SQLite）

### 4.1 表与字段
- **monsters**
  - `id (PK)` 自增
  - `name_final (str, index)` 必填，最终名称
  - `element (str, index)` 元素（如 火/水/土/...）
  - `role (str, index)` 定位（主攻/肉盾/辅助/...）
  - `base_offense/base_survive/base_control/base_tempo/base_pp (float)` 基础向量
  - `explain_json (json)` 规则引擎解释产物（对象）
  - `created_at/updated_at (datetime)`

- **tags**
  - `id (PK)`，`name (unique, index)` 标签名称

- **monster_tag**（多对多关联）
  - `monster_id` + `tag_id` 复合主键

- **import_jobs**
  - `id (PK)`
  - `key (unique, index)` Idempotency-Key
  - `status (str)`：`done/processing/failed`
  - `result_json (json)`：上次导入结果缓存
  - `created_at (datetime)`

- **tasks**
  - `id (uuid, PK)`
  - `type (str)`：如 `recalc`
  - `status (str)`：`pending/running/done/failed`
  - `progress/total (int)`
  - `result_json (json)`：任务结果/错误
  - `created_at (datetime)`

### 4.2 SQLite 设置（在 `db.py` 的 `connect` 钩子中）
- `PRAGMA journal_mode=WAL;`（高并发读取友好）
- `PRAGMA synchronous=NORMAL;`
- `PRAGMA foreign_keys=ON;`

---

## 5. 错误约定与 Trace

- **响应头**：`x-trace-id`（每次请求生成 UUID）。
- **错误体（Problem+JSON 风格）**：
```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "code": "VALIDATION_ERROR",
  "detail": "...",
  "trace_id": "e6b8..."
}
```
- 统一处理：
  - `HTTP_ERROR`（HTTPException）
  - `VALIDATION_ERROR`（Pydantic 校验）
  - `INTERNAL_ERROR`（其他异常）

> 建议前端把 `x-trace-id` 透传到错误提示和诊断面板。

---

## 6. 接口规范（API）

### 6.1 健康检查
- **GET** `/health` → `200 OK`
```json
{
  "ok": true,
  "versions": {"python":"3.x","fastapi":"0.112","sqlalchemy":"2.x"},
  "db_path": "kbxy-dev.db",
  "engine_version": "rules-2025.08.01",
  "counts": {"monsters": 3, "tags": 4}
}
```

### 6.2 妖怪列表与详情
- **GET** `/monsters`
  - **Query**：
    - `q?: string`（名称模糊）
    - `element?: string`、`role?: string`、`tag?: string`
    - `sort?: "offense|survive|control|tempo|pp|name|updated_at"`（默认 `updated_at`）
    - `order?: "asc|desc"`（默认 `desc`）
    - `page?: int`（默认 1）
    - `page_size?: int`（默认 20，最大 200）
  - **200**：
```json
{
  "items": [{
    "id": 1,
    "name_final": "雷霆狼",
    "element": "火",
    "role": "主攻",
    "base_offense": 130,
    "base_survive": 95,
    "base_control": 60,
    "base_tempo": 110,
    "base_pp": 62,
    "tags": ["PP压制","速攻"],
    "explain_json": {"weights": {"offense":1.0}, "formula":"linear", "inputs": {...}}
  }],
  "total": 3,
  "has_more": false,
  "etag": "W/"monsters:3""
}
```
- **GET** `/monsters/{id}` → `200` `MonsterOut`
- **POST** `/monsters` → `201` `MonsterOut`（请求体 `MonsterIn`）
- **PUT** `/monsters/{id}` → `200` `MonsterOut`
- **DELETE** `/monsters/{id}` → `200 {"ok": true}`

### 6.3 标签聚合
- **GET** `/tags?with_counts=true` → `200`：
```json
[{"name":"耐久","count":12},{"name":"控场","count":8}]
```

### 6.4 导入（预览 / 提交）

#### CSV 规范
- **编码**：UTF-8（建议带 BOM）
- **分隔符**：`,` 或 `\t`
- **表头（示例）**：
  `name_final,element,role,base_offense,base_survive,base_control,base_tempo,base_pp,tags`
- **空白清洗**：会将 `NBSP(\u00A0)`、全角空格 `\u3000` 转普通空格。
- **标签字段**：`tags` 可使用分隔符 **`|` / `,` / `;` / 空白** 任意之一，如：`PP压制|速攻`。

#### 预览
- **POST** `/import/preview`（`multipart/form-data`，字段名 `file`）
- **200**：
```json
{
  "columns": ["name_final","element","role","base_offense","base_pp","tags"],
  "total_rows": 523,
  "sample": [{"name_final":"雷霆狼","element":"火","base_offense":"130","tags":"PP压制|速攻"}],
  "hints": ["缺少必填列: ..."]
}
```

#### 提交（**单事务 + 幂等**）
- **POST** `/import/commit`
  - **请求头**：`Idempotency-Key: <字符串>`（可选；相同 key 的重复请求直接返回上次结果）
  - **表单**：同预览（`file` 字段）
- **200**：
```json
{"inserted": 120, "updated": 30, "skipped": 2, "errors": []}
```
- **行为说明**：
  - 执行于 **单个数据库事务**；任一错误将回滚整批写入；
  - “查重原则”：`name_final` +（若提供）`element`；存在则更新，否则插入；
  - 基础数值字段按 `float()` 解析失败记为 `0.0`；
  - `tags` 会按分隔符拆分并 **upsert** 到标签表；
  - 幂等结果会写入 `import_jobs` 以缓存同一 key 的响应。

### 6.5 重算（同步 / 异步）

#### 同步
- **POST** `/recalc`
```json
{
  "ids": [1,2,3],            // 可选；缺省表示全量
  "weights": {"offense": 1.2}, // 可选；示例规则是线性权重
  "persist": true              // 可选；是否回写到 explain_json
}
```
- **200**：
```json
{"affected": 3, "results": [{"id":1,"tags":["强攻","PP压制"],"explain":{...}}]}
```

#### 异步（推荐）
- **POST** `/tasks/recalc`（Body 可选：`{"offense":1.2,...}`，若不传则默认权重）
- **200**：`{"task_id":"<uuid>","status":"pending"}`
- **GET** `/tasks/{id}` → `200`：
```json
{"id":"<uuid>","type":"recalc","status":"running","progress":200,"total":1024,"result":{}}
```
- 任务状态：`pending/running/done/failed`；进度依 `progress/total` 轮询。

---

## 7. 性能与容量（建议值）

- **列表接口**：p95 < 300ms（1 万行级别，单机）  
- **导入**：10 万行在 60s 内完成（本地 SSD）  
- **重算**：1 万行 < 15s（示例规则）  
- **SQLite 维护**：定期 `VACUUM` / `ANALYZE`（大量导入后执行）。

> 以上为经验基线，视硬件与数据规模调整。

---

## 8. 安全与限制（建议）

- **上传限制**：建议反向代理层限制每次导入文件大小（例如 20MB）。  
- **CSV 公式注入**：若后续支持 XLSX，需防止以 `= + - @` 开头的单元格（当前仅 CSV/TSV）。  
- **CORS**：生产环境按域名白名单收敛。  
- **鉴权/权限**：当前为本地单机模式，若对公网开放，请增加鉴权中间件与限流。

---

## 9. 自测清单（手动）

```bash
# 0) 可选：灌入示例数据
python scripts/seed.py

# 1) 健康检查
curl http://127.0.0.1:8000/health

# 2) 导入预览
curl -F "file=@data/sample_monsters.csv" http://127.0.0.1:8000/import/preview

# 3) 导入提交（带幂等）
curl -F "file=@data/sample_monsters.csv"      -H "Idempotency-Key: demo-001"      http://127.0.0.1:8000/import/commit

# 4) 列表查询（含搜索/分页）
curl "http://127.0.0.1:8000/monsters?q=狼&page=1&page_size=20&sort=updated_at&order=desc"

# 5) 同步重算并持久化
curl -X POST "http://127.0.0.1:8000/recalc" -H "Content-Type: application/json"      -d '{"ids":[1,2,3],"weights":{"offense":1.1},"persist":true}'

# 6) 异步重算
curl -X POST "http://127.0.0.1:8000/tasks/recalc" -H "Content-Type: application/json" -d '{"offense":1.1}'
curl "http://127.0.0.1:8000/tasks/<task_id>"
```

---

## 10. 版本与约定

- **OpenAPI**：FastAPI 自动生成，前端可用 `openapi-typescript` 生成类型，避免 `any`。  
- **语义变更**：新增字段/参数请先在 `/import/preview` 与 `/monsters` 的响应中灰度露出，确认前端适配后再强约束。  
- **向后兼容**：新规则引擎上线前建议做 **dry-run 对比**（同一数据下新旧分数/标签分布差异）。

---

## 11. FAQ

- **为何需要 Idempotency-Key？**  
  避免用户重复点击导致重复写入，保证提交幂等性，降低“半成功/重复导入”的概率。

- **`explain_json` 为什么必须是对象？**  
  便于前端展开查看结构化解释（权重、公式、输入），而不是把 JSON 当字符串渲染。

- **能否换数据库？**  
  可以；将 `DATABASE_URL` 替换为 Postgres 等，并改造模型/索引与连接参数。

---

> 文档版本：2025-08-12 · 适配 `kbxy-monsters-pro` 当前后端实现
