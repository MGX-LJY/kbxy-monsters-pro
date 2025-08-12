# kbxy-monsters-pro · 后端开发文档（Standalone）

> 面向后端开发与联调：架构、环境、数据模型、接口、导入策略（幂等 + 单事务）、备份/恢复、批量操作、错误约定与自测。

---

## 1) 概览

- **技术栈**：FastAPI · Pydantic v2 · SQLAlchemy 2.x · SQLite（WAL）
- **运行方式**：本地单机；默认 DB 文件 `kbxy-dev.db` 位于项目根目录
- **核心能力**
  - 妖怪数据 CRUD、检索、排序、分页
  - CSV/TSV **导入预览** + **单事务提交** + **Idempotency-Key 幂等**
  - 规则引擎产出 `explain_json`（含 `raw_stats` 六维 & 自动标签）
  - **备份/恢复**（JSON）与**导出**（CSV）
  - **统计**、**批量删除**、**技能管理**

---

## 2) 目录结构（后端）

```
server/
  app/
    __init__.py
    main.py               # 应用入口（CORS、TraceID、路由、统一异常）
    config.py             # 配置（应用名、CORS、DB 路径）
    db.py                 # SQLAlchemy Engine/Session，SQLite PRAGMA
    middleware.py         # TraceID 中间件（x-trace-id）
    models.py             # Monster / Skill / Tag / ImportJob / Task
    schemas.py            # Pydantic v2 请求/响应模型
    routes/
      health.py
      monsters.py         # 列表/详情/CRUD
      skills.py           # GET/PUT /monsters/{id}/skills
      skills_admin.py     # 可选：技能清理/维护
      importing.py        # 导入预览/提交（幂等）
      tags.py             # 标签聚合
      recalc.py           # 重算（示例规则引擎）
      tasks.py            # 异步任务（可选）
      utils.py            # 小工具路由（可选）
      backup.py           # 统计、导出 CSV、备份/恢复、批删
    services/
      rules_engine.py     # 打分与标签
      monsters_service.py # 列表查询/标签 upsert/解释计算
      skills_service.py   # 技能 upsert / 文本抽取 / 标签派生
      import_service.py   # CSV/TSV 解析、映射、幂等、单事务
```

---

## 3) 快速开始

```bash
# 进入仓库根目录
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt

# 本地启动
uvicorn server.app.main:app --reload --port 8000

# API 文档
# http://127.0.0.1:8000/docs
# http://127.0.0.1:8000/openapi.json
```

**环境变量**

- `KBXY_DB_PATH`：自定义 SQLite 路径（默认 `kbxy-dev.db`）

**CORS**

- 默认允许：`http://localhost:5173`, `http://127.0.0.1:5173`（见 `config.py`）

**SQLite PRAGMA**

- `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`

---

## 4) 数据模型

### 4.1 实体

- **Monster**
  - `id (PK)`、`name_final (str, idx)`、`element (str, idx)`、`role (str, idx)`
  - `base_offense/base_survive/base_control/base_tempo/base_pp (float)`
  - `explain_json (json)`：包含 `raw_stats` 六维和规则解释
  - 关系：`tags (many2many Tag)`、`skills (many2many Skill)`
  - `created_at/updated_at`
- **Tag**
  - `id (PK)`、`name (unique, idx)`
- **Skill**
  - `id (PK)`、`name (idx)`、`description (text)`
  - 去重逻辑在 `skills_service.upsert_skills`
- **ImportJob**
  - `id (PK)`、`key (unique)`、`status`、`result_json`、`created_at`
- **Task**（可选）
  - `id (uuid, PK)`、`type`、`status`、`progress/total`、`result_json`、`created_at`

---

## 5) 接口（摘要）

### 5.1 健康检查

- **GET** `/health` → `200`

### 5.2 列表/详情/CRUD

- **GET** `/monsters`
  - Query：`q?`、`element?`、`role?`、`tag?`
  - `sort? = updated_at|name|offense|survive|control|tempo|pp`（默认 `updated_at`）
  - `order? = asc|desc`（默认 `desc`）
  - 分页：`page`（默认 1）、`page_size`（默认 20，最大 200）
- **GET** `/monsters/{id}`
- **POST** `/monsters`（`MonsterIn`）
- **PUT** `/monsters/{id}`
- **DELETE** `/monsters/{id}`

### 5.3 技能（按怪物）

- **GET** `/monsters/{id}/skills` → `[{ id, name, description }]`
- **PUT** `/monsters/{id}/skills`
  - Body：`{ "skills": [{ "name": "...", "description": "..." }, ...] }`
  - 行为：**覆盖**该怪物当前的技能集合（内部做 upsert + 绑定）

### 5.4 标签聚合

- **GET** `/tags?with_counts=true` → `[{ name, count }]`

### 5.5 统计/导出/备份/恢复/批删（均在 `backup.py`）

- **GET** `/stats`  
  → `{ total, with_skills, tags_total }`
- **GET** `/export/monsters.csv`
  - 尊重筛选：`q/element/role/tag/sort/order`
  - 下载 CSV（含标签列，`|` 分隔）
- **GET** `/backup/export_json`
  - 导出 JSON，结构：
    ```json
    {"monsters":[
      {
        "id":1,"name_final":"...","element":"...","role":"...",
        "base_offense":0,"base_survive":0,"base_control":0,"base_tempo":0,"base_pp":0,
        "raw_stats":{"hp":...,"speed":...,"attack":...,"defense":...,"magic":...,"resist":...,"sum":...},
        "tags":["..."],
        "skills":[{"name":"...","description":"..."}]
      }
    ]}
    ```
- **POST** `/backup/restore_json`
  - Body：上面导出结构（可部分字段）
  - 行为：按 `name_final` + `element?` upsert，覆盖标签与技能集合；回写 `raw_stats` 到 `explain_json`
- **DELETE** `/monsters/bulk_delete`
  - Body：`{ "ids": [1,2,3] }`（Pydantic 使用 `default_factory` 防可变默认）
  - 若上游代理不支持 DELETE 携带 body，可使用 **POST** `/monsters/bulk_delete`（已等价实现）

> 备份实现使用 `selectinload(Monster.tags/skills)`，避免 SQLAlchemy 2.x 在集合 joinedload 时强制 `.unique()` 的问题。

---

## 6) 导入（预览 & 提交）

### 6.1 表头与映射

- **必填**：`name_final`
- **识别字段（多语言/别名）**  
  - 名称：`名称|最终名称|名字|name -> name_final`
  - 元素：`元素|属性|element`
  - 定位：`定位|位置|role`
  - 六维：`体力(hp)|速度(speed)|攻击(attack)|防御(defense)|法术(magic)|抗性(resist)`
  - 标签：`标签|tag|tags`
  - 关键技能：
    - 名称列：`技能|关键技能|skill|skill1|skill2|...`
    - 描述列：`技能说明|关键技能说明|skill_desc|...`（或紧邻右侧 3 列内的“像描述”的文本）
  - 评价/总结（主观）：`说明|总结|评价|描述|效果|介绍 -> summary`（**不**被当作技能描述，只作为侧边“评价”显示）

> 自动清洗空白（`\u00A0`、全角空格）、自动识别分隔符（`,` / `\t` / `;` / `|`），数值解析失败记为 0。

### 6.2 预览

- **POST** `/import/preview`（`multipart/form-data`，字段名 `file`）
- 返回：`{ columns, total_rows, sample, hints }`

### 6.3 提交（单事务 + 幂等）

- **POST** `/import/commit`（同上）
- 可选请求头：`Idempotency-Key: <string>`
  - 相同 Key 的重复提交直接返回上次结果（命中 `import_jobs` 缓存）
- 行为：
  - 单个数据库事务，任一错误回滚整批
  - 按 `name_final` + 可选 `element` 去重，存在即更新
  - 自动计算/持久化：
    - `explain_json.raw_stats = {hp, speed, attack, defense, magic, resist, sum}`
    - `base_*` 由六维映射：`offense=attack`、`survive=hp`、`control=(defense+magic)/2`、`tempo=speed`、`pp=resist`
    - 标签合并：规则引擎 + 技能文本派生 + CSV 标签
  - 技能：提取 `(name, desc)` 对，做 upsert 并绑定；去重按名称

---

## 7) 重算（可选）

- **POST** `/recalc`（同步）
- **POST** `/tasks/recalc` + **GET** `/tasks/{id}`（异步）

> 默认是线性权重示例；上线新规则建议先做 dry-run 对比。

---

## 8) 错误与 Trace

- 响应头：`x-trace-id`
- 错误体（示例）：
  ```json
  {
    "type": "about:blank",
    "title": "Validation Error",
    "status": 422,
    "code": "VALIDATION_ERROR",
    "detail": "...",
    "trace_id": "..."
  }
  ```

---

## 9) 自测清单

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 预览导入
curl -F "file=@data/monsters.csv" http://127.0.0.1:8000/import/preview

# 幂等提交
curl -F "file=@data/monsters.csv" -H "Idempotency-Key: demo-001" http://127.0.0.1:8000/import/commit

# 列表
curl "http://127.0.0.1:8000/monsters?sort=updated_at&order=desc&page=1&page_size=20"

# 导出 CSV（尊重筛选）
curl -OJ "http://127.0.0.1:8000/export/monsters.csv?sort=updated_at&order=desc"

# 备份 JSON
curl -OJ "http://127.0.0.1:8000/backup/export_json"

# 恢复 JSON
curl -X POST -H "Content-Type: application/json" \
     -d @backup.json http://127.0.0.1:8000/backup/restore_json

# 批量删除（DELETE）
curl -X DELETE -H "Content-Type: application/json" \
     -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/monsters/bulk_delete

# 批量删除（POST 兼容）
curl -X POST -H "Content-Type: application/json" \
     -d '{"ids":[4,5]}' http://127.0.0.1:8000/monsters/bulk_delete
```

---

## 10) 版本与约定

- OpenAPI 自动生成，建议前端用 `openapi-typescript` 生成类型
- 新字段/参数请先灰度（响应中露出），确认前端适配再强约束
- 需要切换数据库（Postgres 等）时，更新 `DATABASE_URL` 与索引策略

---

**文档版本**：2025-08-12 · 匹配当前实现  
需要我顺手把这份文档落到仓库（比如新建 `docs/backend.md`）或导出为 PDF/MD 文件吗？