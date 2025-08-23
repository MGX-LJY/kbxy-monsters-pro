---
file: server/app/config.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: []
exposes: [Settings, settings]
---

# config.py · 快速卡片

## TL;DR（30 秒）
- **职责**：集中管理应用基础配置（应用名、数据库文件路径、CORS 白名单）。
- **实现**：Pydantic `BaseModel` + 环境变量 `KBXY_DB_PATH`（仅用于 db_path）。
- **默认值**：`app_name="kbxy-monsters-pro"`；`db_path="kbxy-dev.db"`（相对**当前工作目录**）；`cors_origins=["http://localhost:5173","http://127.0.0.1:5173"]`
- **常见坑**
  1. `db_path` 为**相对路径** → 进程工作目录不同会导致 DB 落盘位置不同。
  2. 仅 `db_path` 通过 `os.getenv` 读取；**`cors_origins` 暂不支持环境变量覆盖**。
  3. 模块导入时完成一次性实例化（`settings = Settings()`），**运行期修改环境变量不会生效**。

## 职责与边界
- **做什么**：提供统一、类型安全的运行时配置对象；供 `main.py` / `db.py` / 业务层读取。
- **不做什么**：不负责配置优先级裁决（`DATABASE_URL` 优先级在 `db.py` 处理）；不负责 .env 解析。

## 公开接口
- `class Settings(BaseModel)`：应用配置模型。
- `settings: Settings`：单例配置对象，供全局导入使用。

## 依赖与数据流
- **上游**：进程环境变量 `KBXY_DB_PATH`（仅影响 `db_path`）。
- **下游**：`main.py` 读取 `cors_origins` 设置 CORS；`db.py` 读取 `db_path`（若未提供 `DATABASE_URL` 时）。
- **备注**：最终 DB 连接优先级通常为 `DATABASE_URL > KBXY_DB_PATH > 默认 "kbxy-dev.db"`（该优先级在 `db.py` 内部实现）。

## 输入 / 输出（Input/Output）
- **输入**
  - 环境变量：`KBXY_DB_PATH`（字符串路径，绝对/相对皆可）
- **输出**
  - `settings.app_name: str`
  - `settings.db_path: str`
  - `settings.cors_origins: list[str]`

## 错误与可观测性
- **配置错误表现**：路径写错或相对路径导致 DB 在意外位置新建；CORS 未包含前端来源导致浏览器跨域失败。
- **定位建议**：在启动日志中打印 `settings.model_dump()`；核对工作目录 `os.getcwd()` 与 `db_path`。

## 示例（最常用 1–2 个）
```py
# 读取配置
from server.app.config import settings

print(settings.model_dump())          # Pydantic v2 推荐
# {'app_name': 'kbxy-monsters-pro', 'db_path': 'kbxy-dev.db', 'cors_origins': [...]}
```

```bash
# 指定 DB 文件到项目根目录（推荐）
KBXY_DB_PATH="$(pwd)/kbxy-dev.db" uvicorn server.app.main:app --reload
```

## 变更指南（How to change safely）
- **新增字段**：在 `Settings` 中添加类型和默认值；确保下游读取点具备后向兼容；更新文档与自测。
- **支持更多环境变量**：若要让 `cors_origins` 支持环境覆盖，需：
  - 方案 A（轻量）：在构造前解析 `os.getenv("CORS_ORIGINS")` 并按逗号拆分。
  - 方案 B（规范）：改用 `pydantic-settings`（`BaseSettings`）与 `.env` 文件，集中管理优先级。
- **避免运行期失效**：如需运行期变更配置，提供显式的 `load_settings()` 工厂并在关键模块中延迟获取。

## 自测清单
- [ ] 不设置环境变量启动，应用可正常读取默认值。
- [ ] 设置 `KBXY_DB_PATH` 为绝对路径，实际 DB 文件落在期望位置。
- [ ] 前端来源在 `cors_origins` 范围内，跨域预检通过。

## 术语与约定
- **工作目录（CWD）**：相对路径均以进程启动时的 `cwd` 为基准。
- **配置优先级**：数据库连接以 `db.py` 的逻辑为准，通常 `DATABASE_URL` 高于本文件的 `db_path`。
