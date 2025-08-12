
# Development Guide — 卡布西游妖怪图鉴 Pro

> 版本：v1.0（文档）  
> 项目代号：`kbxy-monsters`  
> 目标读者：独立开发者（Mac 优先），对 Python / FastAPI / React 有基本了解  
> 文档维护者：你（项目负责人）

---

## 目录

- [1. 项目愿景与范围](#1-项目愿景与范围)
- [2. 系统总览](#2-系统总览)
  - [2.1 架构图（文字版）](#21-架构图文字版)
  - [2.2 模块清单](#22-模块清单)
- [3. 开发环境与快速启动](#3-开发环境与快速启动)
  - [3.1 运行要求（Mac）](#31-运行要求mac)
  - [3.2 一键脚本/命令约定](#32-一键脚本命令约定)
  - [3.3 本地数据库三分法](#33-本地数据库三分法)
  - [3.4 端口与 CORS](#34-端口与-cors)
- [4. 目录结构建议](#4-目录结构建议)
- [5. 数据建模](#5-数据建模)
  - [5.1 实体关系（ER）说明](#51-实体关系er说明)
  - [5.2 表结构定义](#52-表结构定义)
  - [5.3 唯一键与索引](#53-唯一键与索引)
  - [5.4 迁移策略](#54-迁移策略)
- [6. 评分与标签引擎](#6-评分与标签引擎)
  - [6.1 设计目标](#61-设计目标)
  - [6.2 规则文件格式（JSON/YAML）](#62-规则文件格式jsonyaml)
  - [6.3 评分公式（示例）](#63-评分公式示例)
  - [6.4 可解释输出 explain_json](#64-可解释输出-explain_json)
  - [6.5 版本化与重算](#65-版本化与重算)
- [7. API 设计](#7-api-设计)
  - [7.1 统一错误格式](#71-统一错误格式)
  - [7.2 健康检查](#72-健康检查)
  - [7.3 列表与检索](#73-列表与检索)
  - [7.4 详情](#74-详情)
  - [7.5 新增/更新/删除](#75-新增更新删除)
  - [7.6 批量导入 CSV/TSV/XLSX](#76-批量导入-csvtsvxlsx)
  - [7.7 重算分数/标签](#77-重算分数标签)
  - [7.8 标签/技能查字典](#78-标签技能查字典)
- [8. 前端规范（React + Vite + TS + Tailwind）](#8-前端规范react--vite--ts--tailwind)
  - [8.1 技术栈与依赖](#81-技术栈与依赖)
  - [8.2 状态管理与数据访问](#82-状态管理与数据访问)
  - [8.3 UI 布局与交互](#83-ui-布局与交互)
  - [8.4 组件约定](#84-组件约定)
  - [8.5 错误态/空态/加载态](#85-错误态空态加载态)
- [9. 导入流程（带预览、去重、回滚）](#9-导入流程带预览去重回滚)
  - [9.1 字段映射与校验](#91-字段映射与校验)
  - [9.2 去重键与模式](#92-去重键与模式)
  - [9.3 大文件分批与事务](#93-大文件分批与事务)
  - [9.4 失败行导出](#94-失败行导出)
- [10. 搜索与性能](#10-搜索与性能)
  - [10.1 SQLite WAL 与索引](#101-sqlite-wal-与索引)
  - [10.2 全文检索 FTS5（可选）](#102-全文检索-fts5可选)
  - [10.3 ETag/缓存与分页](#103-etag缓存与分页)
- [11. 观测性与调试](#11-观测性与调试)
  - [11.1 后端日志（结构化）](#111-后端日志结构化)
  - [11.2 前端日志与诊断面板](#112-前端日志与诊断面板)
  - [11.3 常见错误与排查手册](#113-常见错误与排查手册)
- [12. 测试与验收](#12-测试与验收)
  - [12.1 基线数据集](#121-基线数据集)
  - [12.2 单元/集成测试建议](#122-单元集成测试建议)
  - [12.3 验收 DoD 清单](#123-验收-dod-清单)
- [13. 发布、备份与回滚](#13-发布备份与回滚)
  - [13.1 版本号与变更日志](#131-版本号与变更日志)
  - [13.2 数据库备份与导出](#132-数据库备份与导出)
  - [13.3 回滚流程](#133-回滚流程)
- [14. 代码风格与协作约定](#14-代码风格与协作约定)
  - [14.1 提交信息规范](#141-提交信息规范)
  - [14.2 分支策略](#142-分支策略)
  - [14.3 目录命名与类型定义](#143-目录命名与类型定义)
- [15. 日常工作节奏与里程碑](#15-日常工作节奏与里程碑)
  - [15.1 三日落地计划](#151-三日落地计划)
  - [15.2 里程碑 M1/M2/M3](#152-里程碑-m1m2m3)
- [16. 安全、权限与限制](#16-安全权限与限制)
- [17. 附录](#17-附录)
  - [A. 基线 CSV 列说明](#a-基线-csv-列说明)
  - [B. 规则文件示例（JSON）](#b-规则文件示例json)
  - [C. explain_json 示例](#c-explain_json-示例)
  - [D. 环境变量样例](#d-环境变量样例)
  - [E. Make 命令建议](#e-make-命令建议)
  - [F. 常见报错速查表](#f-常见报错速查表)

---

## 1. 项目愿景与范围

构建一个 **稳定、可扩展、可解释** 的“卡布西游妖怪图鉴 Pro”本地应用，支持：
- 可视化“筛选/排序/搜索”，并有**可解释**的“评分+标签”系统；
- 快速导入（CSV/TSV/XLSX）与文本解析；
- 强去重（`element+name_final`）、**事务导入**与**失败行导出**；
- 规则可配置（JSON），升级可重算且可追溯（engine_version）；
- 不白屏、错误可读、日志可定位。

**非目标（当前阶段）**
- 不做云端账号、多租户；
- 不做复杂战斗模拟，仅做潜力/定位的评分与标签。

---

## 2. 系统总览

### 2.1 架构图（文字版）

- **前端**（Vite + React + TS + Tailwind）  
  - 页面：列表、详情抽屉、导入对话框、权重调节、可解释面板；
  - 数据：React Query 拉取 API，Zod 进行前端校验；
  - 错误：ErrorBoundary + 全局错误卡片 + 诊断面板（dev）。

- **后端**（FastAPI + Pydantic v2 + SQLAlchemy 2.x + SQLite）  
  - 层次：API 层 / Service 层 / DAO 层 / 规则引擎；
  - 存储：SQLite（WAL），规范化表 + FTS5（可选）；
  - 规则：外置 JSON（热更新），输出 explain_json；
  - 导入：预览→确认→事务导入→摘要。

### 2.2 模块清单

- `client/`：前端应用源代码。
- `server/`：后端服务源代码。
- `rules/`：打分与标签规则 JSON/YAML。
- `data/`：示例 CSV、测试数据、种子数据。
- `scripts/`：开发辅助脚本（备份、导出、重置）。
- `docs/`：文档（本文件、API 声明、ADR）。

---

## 3. 开发环境与快速启动

### 3.1 运行要求（Mac）

- macOS 12+（Apple Silicon 或 Intel）
- Python 3.11 或 3.12（建议固定小版本）
- Node.js 20 LTS（通过 `nvm` 管理）
- SQLite 3（系统内置即可）

> 建议使用 `pyenv`/`uv` + `nvm`，保证版本可复现。

### 3.2 一键脚本/命令约定

建议在根目录提供 `Makefile`（或 `justfile`）：

```makefile
setup: ## 一次性安装后端与前端依赖
\tcd server && python -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt
\tcd client && npm ci

dev: ## 同时启动后端与前端（两个终端分别跑）
\tcd server && source .venv/bin/activate && uvicorn server.app:app --reload --host 127.0.0.1 --port 8000
\t# 另开一个终端：cd client && npm run dev

seed: ## 导入示例数据
\tcd server && source .venv/bin/activate && python seed.py

test:
\t# 预留：pytest / vitest

lint:
\t# 预留：ruff / eslint

build:
\tcd client && npm run build

release:
\t# 预留：打包前端静态产物，生成变更日志
```

### 3.3 本地数据库三分法

- `kbxy-dev.db`（开发）
- `kbxy-test.db`（测试）
- `kbxy-prod.db`（演示/预发布）

> **永不共用**。任何导入/重算在 dev 环境验证通过后再迁移到 prod。

### 3.4 端口与 CORS

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`
- CORS：默认仅放行 `127.0.0.1:5173`，通过环境变量可扩展。

---

## 4. 目录结构建议

```
kbxy-monsters/
├─ client/                     # 前端
│  ├─ src/
│  │  ├─ api/                  # 封装 API（fetch/axios + React Query hooks）
│  │  ├─ components/           # 通用组件
│  │  ├─ features/             # 业务功能（列表/详情/导入/权重）
│  │  ├─ pages/                # 页面路由
│  │  ├─ lib/                  # 工具（zod schema、格式化、日志）
│  │  ├─ types/                # TS 类型（由 OpenAPI 生成或手写）
│  │  └─ main.tsx
│  └─ index.html
├─ server/                     # 后端
│  ├─ app.py                   # FastAPI 入口（路由装配）
│  ├─ db.py                    # engine/session/base 初始化
│  ├─ models.py                # SQLAlchemy ORM 模型
│  ├─ schemas.py               # Pydantic 模型（入参/出参）
│  ├─ services/                # 业务服务（导入/规则/重算）
│  ├─ rules_engine/            # 规则引擎实现
│  ├─ calc.py                  # 评分计算（对 rules_engine 的封装）
│  ├─ seed.py                  # 种子数据
│  ├─ start.sh                 # uvicorn 启动脚本
│  └─ migrations/              # 迁移脚本（alembic 或内置）
├─ rules/                      # JSON/YAML 规则集
├─ data/                       # 示例 CSV/TSV/XLSX
├─ scripts/                    # 备份/导出/重置等脚本
├─ .env.example                # 环境变量样例
└─ README.md / Development.md  # 文档
```

---

## 5. 数据建模

### 5.1 实体关系（ER）说明

- `monsters`（妖怪主表）
  - `element`（金/木/水/火/土）
  - `name_repo`（仓库名）
  - `name_final`（最终名）
  - 六维：`hp,speed,attack,defense,magic,resist,total`
  - `summary`、`role`
  - **基准分**：`base_offense, base_survive, base_control, base_tempo, base_pp`
  - `created_at, updated_at`

- `skills`（技能字典表）
  - `name` 唯一、`category`（物理/法术/辅助…）、`desc`

- `monster_skills`（多对多）
  - `monster_id, skill_id, is_key`

- `tags`（标签字典）
  - `name` 唯一、`desc`

- `monster_tags`（多对多）
  - `monster_id, tag_id, score_bonus`

- `explanations`（解释表）
  - `monster_id, engine_version, explain_json（JSON 列）, updated_at`

### 5.2 表结构定义

> 以下仅为**结构说明**，具体以迁移脚本为准。

```sql
CREATE TABLE monsters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  element TEXT NOT NULL,
  name_repo TEXT,
  name_final TEXT NOT NULL,
  hp INTEGER, speed INTEGER, attack INTEGER,
  defense INTEGER, magic INTEGER, resist INTEGER,
  total INTEGER,
  summary TEXT,
  role TEXT,
  base_offense REAL DEFAULT 0.0,
  base_survive REAL DEFAULT 0.0,
  base_control REAL DEFAULT 0.0,
  base_tempo REAL DEFAULT 0.0,
  base_pp REAL DEFAULT 0.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX u_monster_element_namefinal ON monsters(element, name_final);
CREATE INDEX i_monsters_namefinal ON monsters(name_final);
CREATE INDEX i_monsters_role ON monsters(role);
CREATE INDEX i_monsters_element ON monsters(element);

CREATE TABLE skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  category TEXT,
  desc TEXT
);

CREATE TABLE monster_skills (
  monster_id INTEGER NOT NULL REFERENCES monsters(id) ON DELETE CASCADE,
  skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
  is_key INTEGER DEFAULT 0,
  PRIMARY KEY (monster_id, skill_id)
);

CREATE TABLE tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  desc TEXT
);

CREATE TABLE monster_tags (
  monster_id INTEGER NOT NULL REFERENCES monsters(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  score_bonus REAL DEFAULT 0.0,
  PRIMARY KEY (monster_id, tag_id)
);

CREATE TABLE explanations (
  monster_id INTEGER NOT NULL REFERENCES monsters(id) ON DELETE CASCADE,
  engine_version TEXT NOT NULL,
  explain_json TEXT NOT NULL, -- 存储 JSON 字符串，但**API 层务必以 JSON 对象返回**
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (monster_id, engine_version)
);
```

> 重要：`explain_json` 虽然底层可用 TEXT 存储，但 API 返回时必须是字典（JSON 对象），避免“字符串被当对象解析”导致 Pydantic 报错。

### 5.3 唯一键与索引

- **唯一键**：`(element, name_final)`，用于导入时**去重**与**更新定位**。
- 索引：
  - `name_final`、`element`、`role` 单列索引（加快筛选/排序）
  - （可选）FTS5 虚拟表对 `name_* / summary / skills.desc` 做全文检索。

### 5.4 迁移策略

- 使用 Alembic 或自定义 `schema_version` 表；
- 每次改表：编写**升级**与**回滚**脚本；
- 首次启动：若无表→自动创建，若表老版本→执行迁移；
- 迁移完成后：`PRAGMA user_version` 更新。

---

## 6. 评分与标签引擎

### 6.1 设计目标

- 规则可配置、可版本化（`engine_version`）；
- 输出**可解释**：每一分/每一标签都能追溯到规则；
- 纯后端模块，易做单元测试。

### 6.2 规则文件格式（JSON/YAML）

见附录 **B** 示例。主要包含：
- `numeric_rules`: 对六维阈值/组合的判定；
- `text_rules`: 关键词/正则从技能与总结命中；
- `tag_mappings`: 命中规则 → 标签名及加分；
- `weights`: 评分公式中的项权重；
- `engine_version`: 当前规则集版本号。

### 6.3 评分公式（示例）

> 仅示例，可在规则文件中配置。

- `base_offense = 0.5*attack + 0.35*magic + 0.15*speed + Σ(标签进攻向bonus)`  
- `base_survive = 0.4*hp + 0.35*defense + 0.25*resist + Σ(标签生存向bonus)`  
- `base_control = 0.4*speed + 文本控制命中×权值 + Σ(控制bonus)`  
- `base_tempo = 0.6*speed + 0.4*命中/先手类关键词×权值`  
- `base_pp = PP 压制类命中×权值`

### 6.4 可解释输出 explain_json

- `matched_rules[]`: 命中的规则（含类型、来源字段、原文片段/正则 group）；
- `score_breakdown`: 每个维度的数值贡献、标签贡献；
- `tags[]`: 标签名、命中规则列表、score_bonus；
- `weights`: 计算时使用的权重快照；
- `engine_version`: 规则版本号；
- `display_scores`: 若带权重参数计算的展示分。

详见附录 **C**。

### 6.5 版本化与重算

- 规则升级 → `engine_version` 变更；
- 提供 `/recalc` 接口：支持按 ID 集合或筛选条件批量重算；
- 可选 `persist=true` 将新基准分与新解释写回表；
- 变更前后**对比视图**（前端）用于验收。

---

## 7. API 设计

> 返回统一为 JSON，字符集 UTF-8。

### 7.1 统一错误格式

`Content-Type: application/problem+json`：

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 400,
  "code": "VALIDATION_ERROR",
  "detail": "field 'element' is required",
  "trace_id": "e.g. 2025-08-12T10:20:30Z-abc123"
}
```

### 7.2 健康检查

`GET /health` →

```json
{
  "ok": true,
  "versions": { "python": "3.12", "fastapi": "x.y", "sqlalchemy": "x.y" },
  "db_path": "kbxy-dev.db",
  "engine_version": "rules-2025.08.01",
  "counts": { "monsters": 123, "skills": 220, "tags": 40 }
}
```

### 7.3 列表与检索

`GET /monsters`

**查询参数**：
- `q`: 关键字（可触发 FTS）
- `element`: `金|木|水|火|土`
- `role`: `主攻|肉盾|辅助|通用|...`
- `tag`: 标签名（支持多值 `,` 分隔）
- `sort`: `offense|survive|control|tempo|pp|name|updated_at`
- `order`: `asc|desc`（默认 `desc`）
- `page`: 页码（默认 1）
- `page_size`: 每页条数（默认 20，上限 200）

**响应**：
```json
{
  "items": [
    {
      "id": 1,
      "element": "金",
      "name_repo": "大块咪",
      "name_final": "九天战猫",
      "hp": 110, "speed": 92, "attack": 114, "defense": 102, "magic": 90, "resist": 93, "total": 601,
      "summary": "…",
      "role": "主攻",
      "base_offense": 150.0,
      "base_survive": 133.0,
      "base_control": 81.8,
      "base_tempo": 100.0,
      "base_pp": 58.0,
      "tags": ["PP压制","速攻"],
      "updated_at": "2025-08-12T12:00:00Z"
    }
  ],
  "total": 123,
  "has_more": true,
  "etag": "W/\"monsters:sha1:...\""
}
```

### 7.4 详情

`GET /monsters/{id}` →
- 基础信息 + 关联 `skills[]`（含 `is_key`）
- 关联 `tags[]`（含 `score_bonus`）
- 最新 `explain_json`（对象，不是字符串）

### 7.5 新增/更新/删除

- `POST /monsters`：新增单个；入参可为**结构化表单**或**原始文本**（`raw_text` 字段）。服务端负责解析、规则命中、评分、落库。
- `PUT /monsters/{id}`：全量更新。
- `PATCH /monsters/{id}`：部分更新。
- `DELETE /monsters/{id}`：删除并级联清理 `monster_skills/monster_tags/explanations`。

### 7.6 批量导入 CSV/TSV/XLSX

- `POST /import/preview`：上传文件 → 返回解析预览、字段映射建议、去重冲突统计；
- `POST /import/commit?mode=upsert&dedup_by=element,name_final`：确认后提交事务导入；

**响应摘要**：
```json
{
  "inserted": 20,
  "updated": 12,
  "skipped": 3,
  "errors": [
    { "row": 37, "error": "missing required field: name_final" }
  ]
}
```

### 7.7 重算分数/标签

- `POST /recalc`：按 ID 列表或筛选条件重算；参数 `persist=true` 控制是否写回；
- 支持带临时 `weights`（仅返回展示用，不改库）。

### 7.8 标签/技能查字典

- `GET /tags?with_counts=true`：标签字典与计数；
- `GET /skills?q=`：技能模糊搜索（用于“添加技能”下拉）。

---

## 8. 前端规范（React + Vite + TS + Tailwind）

### 8.1 技术栈与依赖

- Vite + React + TypeScript
- Tailwind（**PostCSS 本地构建，不用 CDN**）
- React Query（数据获取/缓存/重试）
- React Hook Form + Zod（表单与校验）
- Radix UI / Headless UI（可选：对话框、抽屉等基础交互）
- 日期与数字处理：dayjs / numeral（可选）

### 8.2 状态管理与数据访问

- 首选 **React Query hook**：`useMonsters`, `useMonsterDetail`, `useImportPreview`, `useRecalc`；
- 统一错误拦截 → toast + 错误卡片；
- GET 列表使用 `keepPreviousData` 优化翻页；
- 详情抽屉使用 `enabled: id!=null` 的懒加载。

### 8.3 UI 布局与交互

- 顶栏：API 状态、数据库名称、权重滑杆、功能按钮（➕ 添加 / 📥 导入 / ♻ 重算）；
- 左侧：元素/角色/标签过滤；
- 中间：卡片/表格切换；
- 右侧：详情抽屉（种族值卡片、技能卡片、标签 chips、解释面板按钮）。

### 8.4 组件约定

- 所有弹窗支持 `onOpenChange` 与 ESC 关闭；
- 表单有 `Reset` 按钮与用户确认；
- 导入对话框：3 步 UI（选择文件→映射/预览→确认导入）。

### 8.5 错误态/空态/加载态

- **骨架屏**：列表行骨架、详情骨架；
- **空态**：提示“导入 CSV”并带按钮；
- **错误态**：展示错误 title+detail+trace_id，并提供“复制诊断”。

---

## 9. 导入流程（带预览、去重、回滚）

### 9.1 字段映射与校验

- 自动猜测字段（中英别名），允许用户调整；
- 必填：`element, name_final`（以及六维中至少 HP/Speed/Attack/Defense/Magic/Resist 的合理组合）；
- 文本解析：允许直接粘贴“表格行/自然语言段落”，解析出**元素/名称/六维/技能（最多两条）**。

### 9.2 去重键与模式

- 去重键默认：`element + name_final`；
- 导入模式：
  - `insert_only`：存在跳过；
  - `upsert`：存在更新（可选“仅更新空字段/全部覆盖/按列指定”）；
  - `replace_all`：清空后全量导入（需确认）。

### 9.3 大文件分批与事务

- 分批 1000 行/事务；
- 任一批出错 → 整批回滚；
- 汇总统计到响应。

### 9.4 失败行导出

- 返回 `errors[]`，并可提供 `errors.csv` 下载；
- 错误类型：字段缺失、格式不合法、违反唯一键。

---

## 10. 搜索与性能

### 10.1 SQLite WAL 与索引

- 启用 WAL：`PRAGMA journal_mode=WAL;`  
- 建立必要索引（见 §5.3）；
- 分页策略：`LIMIT/OFFSET`，大页时可改用“基于游标”的分页。

### 10.2 全文检索 FTS5（可选）

- 新建 FTS5 虚拟表，索引 `name_repo,name_final,summary,skills.desc`；
- 搜索 `q` 时先查 FTS5，返回匹配 `rowid` 再回主表。

### 10.3 ETag/缓存与分页

- 列表响应带 `etag`；
- 前端 If-None-Match，减少重复渲染。

---

## 11. 观测性与调试

### 11.1 后端日志（结构化）

JSON Lines：`ts, level, method, path, latency_ms, status, error, trace_id`。  
建议将 `trace_id` 回传到响应头/体，前端日志带同一个 ID，便于串联排查。

### 11.2 前端日志与诊断面板

- 统一前缀 `[KBXY]`；
- 诊断面板（dev）显示：当前过滤条件、最近请求、健康状态、规则版本；
- 提供“复制诊断串”。

### 11.3 常见错误与排查手册

- **`no such table: monsters`**：未执行迁移或 DB 路径不对 → 跑初始化脚本/迁移，检查 `DB_PATH`；
- **`ModuleNotFoundError: server`**：相对导入位置错，确保以包形式运行或改绝对导入；
- **`ImportError: cannot import name 'recalc_scores'`**：函数名/导出不一致，核对 `calc.py` 与 `app.py`；
- **Pydantic `dict_type` 错误**：`explain_json` 以字符串返回，被当对象解析 → 确保 API 返回 JSON 对象；
- **前端白屏**：Tailwind CDN 警告/构建失败/JSON 解析失败 → 切换本地 PostCSS，ErrorBoundary 包裹路由，控制台查具体错误。

---

## 12. 测试与验收

### 12.1 基线数据集

- 从真实数据挑 20–50 条覆盖常见元素/角色/技能；
- 作为**金标准**，每次发版都导入比对分与标签不意外漂移。

### 12.2 单元/集成测试建议

- 单元：文本解析（多格式）、规则命中（边界/冲突）、去重逻辑；
- 集成：导入预览→提交→列表→详情→重算；
- 性能：1k 条列表查询 < 100ms（本地）。

### 12.3 验收 DoD 清单

- 有迁移脚本与回滚说明；
- 基线集导入成功（无重复/无异常）；
- 列表/详情/导入/重算全链路可用；
- 错误/空态/骨架屏完善；
- 日志可定位（trace_id 一致）。

---

## 13. 发布、备份与回滚

### 13.1 版本号与变更日志

- 语义化：`MAJOR.MINOR.PATCH`；
- 每次发布更新 `CHANGELOG.md`。

### 13.2 数据库备份与导出

- 备份：复制 `kbxy-prod.db` 到 `backups/`（带日期戳）；
- 导出：`/export/csv`（全量导出 ZIP）。

### 13.3 回滚流程

- 代码回滚到上一个 tag；
- DB 用备份恢复或执行回滚迁移；
- 重新导入“基线数据集”验证。

---

## 14. 代码风格与协作约定

### 14.1 提交信息规范

- Conventional Commits：`feat/fix/refactor/chore/docs/test` 等；
- 示例：`feat(import): add preview & dedup by (element,name_final)`。

### 14.2 分支策略

- Trunk-based：`main` 稳定，短期 `feat/xxx`；
- 合并前必须本地跑 `make test`（或至少样例用例）。

### 14.3 目录命名与类型定义

- 小写短横线/下划线；
- TS 类型统一放 `client/src/types`，后端 Pydantic schema 与之对齐。

---

## 15. 日常工作节奏与里程碑

### 15.1 三日落地计划

- **Day 1**：表结构与迁移；只读 API（列表/详情）；基本 UI；无白屏。
- **Day 2**：导入预览→提交→摘要；去重模式；失败行导出。
- **Day 3**：规则 JSON 初版；评分/标签/解释面板；重算入口。

### 15.2 里程碑 M1/M2/M3

- **M1（1–2 天）**：稳定基线，导入基础版，评分（数值规则）。
- **M2（2–3 天）**：文本规则、标签体系、解释面板、FTS 搜索（可选）。
- **M3（1–2 天）**：导出、诊断面板、回归测试与发布流程。

---

## 16. 安全、权限与限制

- CORS 默认仅允许 `127.0.0.1:5173`；
- 上传大小限制（如 10MB），校验文件类型；
- 输入清洗与长度限制，防止 UI 异常；
- 本地应用，无账户系统（后续可加）。

---

## 17. 附录

### A. 基线 CSV 列说明

```csv
element,name_repo,name_final,hp,speed,attack,defense,magic,resist,total,summary,role,tags,skill1_name,skill1_desc,skill2_name,skill2_desc
金,大块咪,九天战猫,110,92,114,102,90,93,601,"消耗PP每次一次或两次,提攻防降速",主攻,"PP压制,速攻","浑厚之爪","先手，随机减少对手所有技能的使用次数一或两次","凶煞","自身攻击，防御各提高一级，同时令对手速度下降两级"
```

### B. 规则文件示例（JSON）

```json
{
  "engine_version": "rules-2025.08.01",
  "weights": {
    "offense": { "attack": 0.5, "magic": 0.35, "speed": 0.15 },
    "survive": { "hp": 0.4, "defense": 0.35, "resist": 0.25 },
    "control": { "speed": 0.4, "text": 0.6 },
    "tempo": { "speed": 0.6, "text": 0.4 },
    "pp": { "text": 1.0 }
  },
  "numeric_rules": [
    { "id": "atk_110", "if": { "attack": { "gte": 110 } }, "then": { "tags": [{ "name": "暴击潜力", "bonus": 6 }] } },
    { "id": "spd_110", "if": { "speed": { "gte": 110 } }, "then": { "tags": [{ "name": "速攻", "bonus": 7 }] } },
    { "id": "tank_mix", "if": { "hp": { "gte": 115 }, "defense": { "gte": 100 }, "resist": { "gte": 95 } }, "then": { "tags": [{ "name": "耐久", "bonus": 8 }] } }
  ],
  "text_rules": [
    { "id": "pp_suppress", "match": "减少对手.*技能的使用次数", "fields": ["skill_desc","summary"], "then": { "tags": [{ "name": "PP压制", "bonus": 7 }] } },
    { "id": "dizzy", "match": "昏迷|眩晕|窒息", "fields": ["skill_desc","summary"], "then": { "tags": [{ "name": "控制", "bonus": 5 }] } },
    { "id": "clean_buff", "match": "消除对方.*增益", "fields": ["skill_desc","summary"], "then": { "tags": [{ "name": "消增益", "bonus": 6 }] } },
    { "id": "self_heal", "match": "回复.*HP|吸血", "fields": ["skill_desc","summary"], "then": { "tags": [{ "name": "自回复", "bonus": 4 }] } }
  ],
  "tag_mappings": {
    "PP压制": { "affects": ["pp","tempo"] },
    "速攻": { "affects": ["offense","tempo"] },
    "控制": { "affects": ["control","tempo"] },
    "耐久": { "affects": ["survive"] },
    "消增益": { "affects": ["control"] },
    "自回复": { "affects": ["survive"] }
  }
}
```

### C. explain_json 示例

```json
{
  "engine_version": "rules-2025.08.01",
  "matched_rules": [
    { "id": "atk_110", "type": "numeric", "field": "attack", "value": 114, "tags": ["暴击潜力"] },
    { "id": "pp_suppress", "type": "text", "field": "skill_desc", "snippet": "先手，随机减少对手所有技能的使用次数一或两次", "tags": ["PP压制"] }
  ],
  "score_breakdown": {
    "offense": { "base": 150.0, "tags_bonus": 6.0, "final": 156.0 },
    "survive": { "base": 133.0, "tags_bonus": 0.0, "final": 133.0 },
    "control": { "base": 81.8, "tags_bonus": 0.0, "final": 81.8 },
    "tempo": { "base": 100.0, "tags_bonus": 7.0, "final": 107.0 },
    "pp": { "base": 58.0, "tags_bonus": 7.0, "final": 65.0 }
  },
  "tags": [
    { "name": "暴击潜力", "score_bonus": 6.0, "matched": ["atk_110"] },
    { "name": "PP压制", "score_bonus": 7.0, "matched": ["pp_suppress"] }
  ]
}
```

### D. 环境变量样例

```
# server/.env
DB_PATH=./kbxy-dev.db
CORS_ORIGINS=http://127.0.0.1:5173
MAX_UPLOAD_MB=10
ENGINE_RULES_PATH=./rules/rules-2025.08.01.json
```

### E. Make 命令建议

- `make setup`：安装依赖
- `make dev`：前后端开发模式（分终端）
- `make seed`：导入示例数据
- `make build`：前端构建
- `make lint` / `make test`：质量检查
- `make release`：打包/生成变更日志（预留）

### F. 常见报错速查表

| 报错 | 可能原因 | 解决方案 |
|---|---|---|
| `sqlite3.OperationalError: no such table: monsters` | 未迁移/DB 路径不对 | 执行迁移或初始化；检查 `DB_PATH` |
| `ImportError: cannot import name 'recalc_scores'` | 函数名不一致 | 对齐 `calc.py` 导出与 `app.py` 引用 |
| `ModuleNotFoundError: server` | 包结构/相对导入错误 | 以包运行或改绝对导入；`uvicorn server.app:app` |
| Pydantic `dict_type` 错误 | 后端把 JSON 当字符串返回 | 确保 API 返回 JSON 对象（`object`），不要字符串 |
| 前端白屏 + Tailwind CDN 警告 | 使用了 `cdn.tailwindcss.com` | 使用本地 PostCSS 构建 Tailwind |
| 导入后重复数据 | 未设置唯一键/去重策略 | 设置唯一键 `(element,name_final)`；导入模式选 `upsert` |
| 详情抽屉一直加载 | 详情接口 500/JSON 解析失败 | 检查 `/monsters/{id}`，控制台与后端日志中的 `trace_id` |

---

> 本文档旨在把“项目怎么做好”讲全讲透：从环境、表结构、API、规则、导入、观测、测试、发布、回滚到日常节奏。建议你把它放在仓库根目录，作为**开发者权威指南**。如需补充“API 示例响应的精确 OpenAPI/JSON Schema”，可以在后端实现后通过 `FastAPI` 自动生成并回填到本文件。
