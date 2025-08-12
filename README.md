# 卡布妖怪图鉴 Pro（Kabu Monster Dex）

> **Repo**: `kbxy-monsters-pro` · FastAPI + React + SQLite · 单机可用，支持 CSV 导入、评分/标签引擎、检索与可解释性

## ✨ Features
- 🧩 **妖怪数据管理**：列表、详情、增删改查、标签管理；
- 📥 **CSV 导入（预览/提交）**：支持去重与更新统计；
- 🧠 **评分与标签解释**：规则引擎输出 `explain_json`；
- 🔍 **检索与筛选**：按元素、定位、标签与关键字；
- 🩺 **健康检查**：版本、计数、引擎版本等；
- 🧰 **脚本工具**：备份/恢复、CSV 规范化、种子数据；

## 🧱 Tech Stack
- Backend：FastAPI · Pydantic v2 · SQLAlchemy 2.x · SQLite(WAL)
- Frontend：Vite · React · TypeScript · React Query · RHF · Zod · Tailwind（本地构建）

## 🚀 Quick Start (macOS)
```bash
# 1) 后端
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
uvicorn server.app.main:app --reload --port 8000

# 2) 前端（另开一个终端）
cd client
npm i
npm run dev  # 默认 http://localhost:5173
```

> 如果你看到前端白屏，请先检查浏览器控制台是否有网络报错，并确认**没有使用 CDN 版 Tailwind**，本项目已内置本地构建。

## 📚 API 概览
- `GET /health` 健康检查
- `GET /monsters` 列表与检索（分页/排序/筛选）
- `GET /monsters/{id}` 详情
- `POST /monsters` 新增 · `PUT /monsters/{id}` 更新 · `DELETE /monsters/{id}` 删除
- `POST /import/preview` 预览导入文件（CSV/TSV）
- `POST /import/commit` 提交导入（当前实现需再次上传文件）
- `POST /recalc` 重算分数/标签（演示版）
- `GET /tags` 标签字典与计数

详见 `docs/Development.md`。

## 📂 Project Structure
```
kbxy-monsters-pro/
├─ README.md
├─ LICENSE
├─ .gitignore
├─ Makefile
├─ docs/Development.md
├─ server/
│  ├─ requirements.txt
│  └─ app/
│     ├─ main.py
│     ├─ db.py
│     ├─ models.py
│     ├─ schemas.py
│     ├─ config.py
│     ├─ services/
│     │  ├─ monsters_service.py
│     │  ├─ import_service.py
│     │  └─ rules_engine.py
│     └─ routes/
│        ├─ health.py
│        ├─ monsters.py
│        ├─ importing.py
│        ├─ tags.py
│        └─ recalc.py
├─ client/ (Vite + React + TS + Tailwind)
├─ rules/ (规则文件)
├─ data/ (示例 CSV)
└─ scripts/ (备份、恢复、种子、CSV 规范化)
```

## 🔐 Notes
- 本项目默认**本地单机**使用；如要公网部署，请自行加上鉴权/限流/CORS 白名单等；
- 导入支持 CSV/TSV，XLSX 可先导出为 CSV 再导入（或自行扩展 `import_service.py`）；
- 请确保 CSV 为 **UTF-8** 编码，分隔符`,` 或 `\t`，表头示例参见 `data/sample_monsters.csv`。

## 📝 License
MIT © 2025 Doctor
