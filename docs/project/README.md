# KBXY Monsters Pro - 专业级口袋妖怪图鉴管理系统

## 项目概述

KBXY Monsters Pro是一个功能完整的口袋妖怪图鉴管理系统，采用现代化的前后端分离架构，为用户提供全方位的妖怪数据管理、AI图片处理、智能分析和数据导入等功能。项目集成了多项先进技术，包括AI图片超分辨率放大、智能评分系统、数据爬取引擎和完善的备份恢复机制。

**设计理念**：打造一个高性能、易用性强、功能丰富的妖怪图鉴管理平台，同时保持单机部署的简洁性和生产环境的可扩展性。

## 核心特性

### 🧩 妖怪数据管理
- **全面的数据管理**：支持妖怪信息的增删改查，包括基础属性、技能、标签等
- **智能搜索筛选**：按属性、名称、技能、标签等多维度快速检索
- **属性系统**：完整的元素属性克制关系计算和展示
- **技能管理**：技能数据库管理，支持技能效果计算和学习列表

### 📥 数据导入导出
- **CSV/TSV导入**：支持批量数据导入，智能去重和数据验证
- **预览机制**：导入前预览数据，确保数据质量
- **数据标准化**：自动处理格式差异，确保数据一致性
- **导出功能**：支持多种格式的数据导出

### 🤖 AI图片处理
- **Real-ESRGAN集成**：AI驱动的图片超分辨率放大技术
- **批量处理**：支持大量图片的自动化处理
- **GUI工具**：用户友好的桌面图片处理界面
- **格式支持**：支持多种图片格式的处理和转换

### 🧠 智能分析系统

- **评分引擎**：智能评分系统，输出详细的解释信息
- **标签系统**：支持buf/deb/util等多种标签分类
- **数据挖掘**：从大量数据中发现有价值的模式和关系

### 🔍 高级检索功能
- **多维度筛选**：按元素、定位、标签、技能等组合筛选
- **实时搜索**：响应式搜索，即时显示结果
- **分页优化**：高效的分页机制，支持大数据量展示
- **排序功能**：按多种维度排序，满足不同查看需求

### 🛠️ 管理工具
- **数据备份恢复**：完善的数据库备份和恢复机制
- **健康监控**：系统状态监控和性能指标展示
- **数据爬取**：自动化的外部数据源爬取功能
- **开发工具**：丰富的脚本工具支持开发和维护

## 快速开始

### 1. 环境要求

**系统要求**：
- 操作系统：macOS、Linux、Windows
- Python：3.9+ （推荐 3.11）
- Node.js：16+ （推荐 18 LTS）
- 内存：8GB+（AI图片处理需要更多内存）
- GPU：可选，用于AI图片处理加速

**依赖环境**：
```bash
# Python 环境
python3 -m pip install --upgrade pip
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Node.js 环境
node --version  # 确认 16+
npm --version   # 或使用 yarn
```

### 2. 安装和配置

**后端设置**：
```bash
# 1. 克隆项目
git clone https://github.com/username/kbxy-monsters-pro.git
cd kbxy-monsters-pro

# 2. 安装Python依赖
cd server
pip install -r requirements.txt

# 3. 数据库初始化
python -m app.db  # 创建数据库表

# 4. 启动后端服务
uvicorn app.main:app --reload --port 8000
# 或使用脚本：./start-bg.sh
```

**前端设置**：
```bash
# 1. 安装Node.js依赖
cd client
npm install

# 2. 启动开发服务器
npm run dev

# 3. 构建生产版本（可选）
npm run build
```

### 3. 项目配置和初始化

**环境配置**：
```bash
# 1. 创建配置文件
cp server/app/config.example.py server/app/config.py

# 2. 配置数据库路径（可选）
# 编辑 config.py 中的 DATABASE_URL

# 3. 初始化示例数据（可选）
python scripts/seed_from_export.py data/sample_monsters.csv

# 4. 配置AI模型（可选）
# 下载 Real-ESRGAN 模型到 models/ 目录
```

**验证安装**：
```bash
# 1. 检查后端健康状态
curl http://localhost:8000/health

# 2. 检查前端访问
# 浏览器访问 http://localhost:5173

# 3. 检查API文档
# 浏览器访问 http://localhost:8000/docs
```

## 项目状态

**当前版本**: v2.0.0

**开发状态**：
- ✅ **核心功能完成**：妖怪数据管理、搜索筛选、数据导入导出
- ✅ **前端界面完善**：现代化React界面，响应式设计
- ✅ **AI图片处理**：Real-ESRGAN集成，支持批量处理
- ✅ **数据管理工具**：备份恢复、数据爬取、健康监控
- 🔄 **性能优化中**：数据库查询优化、缓存机制改进
- 📋 **待开发功能**：用户系统、权限管理、API限流

**稳定性评估**：
- 💚 **生产就绪**：核心功能稳定，经过充分测试
- 💛 **Beta功能**：AI图片处理、数据爬取功能
- 🔴 **实验性功能**：实时协作、云端同步

## 技术架构

### 后端架构
```
FastAPI Application
├── API Gateway Layer
│   ├── Routes (monsters, skills, types, images, etc.)
│   ├── Middleware (CORS, Auth, Logging)
│   └── Error Handling
├── Business Logic Layer
│   ├── Services (monsters_service, crawler_service, etc.)
│   ├── AI Processing (image_service, Real-ESRGAN)
│   └── Data Processing (normalization)
├── Data Access Layer
│   ├── ORM Models (SQLAlchemy)
│   ├── Database Connection (SQLite)
│   └── Migration Scripts
└── Infrastructure
    ├── Configuration Management
    ├── Logging and Monitoring
    └── Backup and Recovery
```

### 前端架构
```
React Application
├── Application Layer
│   ├── App Component (Root)
│   ├── Error Boundaries
│   └── Global State (Context API)
├── Page Layer
│   └── MonstersPage (Main Interface)
├── Component Layer
│   ├── Business Components (CardGrid, Drawer, etc.)
│   ├── UI Components (Modal, Toast, etc.)
│   └── Layout Components (TopBar, SideDrawer)
├── Data Layer
│   ├── API Client (React Query)
│   ├── Type Definitions (TypeScript)
│   └── State Management
└── Build Layer
    ├── Vite (Build Tool)
    ├── TailwindCSS (Styling)
    └── TypeScript (Type Safety)
```

### 技术栈详情
- **后端**：FastAPI + SQLAlchemy + SQLite + Pydantic + aiofiles
- **前端**：React 18 + TypeScript + Vite + TailwindCSS + React Query
- **AI处理**：Real-ESRGAN + Python PIL + GPU加速
- **数据库**：SQLite (WAL模式) + 自动备份
- **部署**：Uvicorn + Nginx + systemd + Docker (可选)

## 使用示例

### API使用示例

**获取妖怪列表**：
```bash
# 基础查询
curl "http://localhost:8000/api/monsters?page=1&size=20"

# 按属性筛选
curl "http://localhost:8000/api/monsters?type1=fire&type2=flying"

# 搜索查询
curl "http://localhost:8000/api/monsters?search=皮卡丘"

# 复合筛选
curl "http://localhost:8000/api/monsters?tags=buf&min_hp=100&sort=hp desc"
```

**创建新妖怪**：
```bash
curl -X POST "http://localhost:8000/api/monsters" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "自定义妖怪",
    "type1": "electric",
    "type2": null,
    "hp": 100,
    "attack": 120,
    "defense": 80,
    "sp_attack": 150,
    "sp_defense": 90,
    "speed": 110
  }'
```

### 前端使用示例

**React组件使用**：
```tsx
import { useMonsters } from './api';
import { MonsterCardGrid } from './components';

function MonstersPage() {
  const { data: monsters, isLoading } = useMonsters({
    page: 1,
    size: 20,
    type1: 'fire'
  });

  if (isLoading) return <div>Loading...</div>;

  return (
    <div>
      <h1>Fire-type Monsters</h1>
      <MonsterCardGrid monsters={monsters?.items || []} />
    </div>
  );
}
```

### AI图片处理示例

**GUI工具使用**：
```bash
# 启动图片处理GUI
python upscaler_gui.py
```

**批量处理脚本**：
```bash
# 批量放大图片
python upscale_batch.py --input_dir ./images/original --output_dir ./images/4x --scale 4

# 指定GPU设备
python upscale_batch.py --input_dir ./images --device cuda:0 --batch_size 4
```

### 数据管理示例

**数据库备份**：
```bash
# 创建备份
python scripts/backup_sqlite.py

# 恢复备份
python scripts/restore_sqlite.py backup_20240101_120000.db

# 从CSV导入数据
python scripts/seed_from_export.py data/new_monsters.csv
```

## 开发路线图

### 已完成 (v2.0.0)
- ✅ 核心妖怪数据管理系统
- ✅ React前端界面
- ✅ AI图片处理集成
- ✅ 数据导入导出功能
- ✅ 搜索和筛选系统
- ✅ 备份恢复机制

### 进行中 (v2.1.0)
- 🔄 性能优化和缓存系统
- 🔄 API文档完善
- 🔄 错误处理和日志系统
- 🔄 单元测试覆盖

### 计划中 (v2.2.0)
- 📋 用户认证和权限系统
- 📋 API限流和安全增强
- 📋 实时通知系统
- 📋 数据可视化图表

### 未来版本 (v3.0.0+)
- 🚀 微服务架构重构
- 🚀 云端部署支持
- 🚀 移动端应用
- 🚀 机器学习推荐系统
- 🚀 实时协作功能
- 🚀 插件系统

## 贡献指南

我们欢迎社区贡献！请遵循以下流程：

### 开发流程
1. **Fork项目**：在GitHub上fork本项目
2. **创建分支**：`git checkout -b feature/your-feature-name`
3. **开发调试**：确保所有测试通过
4. **提交代码**：`git commit -m "Add: your feature description"`
5. **推送分支**：`git push origin feature/your-feature-name`
6. **创建PR**：在GitHub上创建Pull Request

### 代码规范
```bash
# Python代码检查
cd server
black . --line-length 88
flake8 . --max-line-length 88
mypy .

# TypeScript代码检查
cd client
npm run lint
npm run type-check
```

### 测试要求
```bash
# 后端测试
cd server
pytest tests/ -v --cov=app

# 前端测试
cd client
npm run test
npm run test:e2e
```

### 提交规范
使用约定式提交格式：
- `feat: 新增功能`
- `fix: 修复bug`
- `docs: 文档更新`
- `style: 代码格式调整`
- `refactor: 代码重构`
- `test: 测试相关`
- `chore: 构建/工具相关`

### 代码审查
所有PR都需要通过代码审查：
- 功能完整性检查
- 代码质量评估
- 性能影响分析
- 安全性审查
- 文档完整性

## 许可证

本项目采用 **MIT License** 开源协议。

```
MIT License

Copyright (c) 2025 KBXY Monsters Pro Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 第三方许可
- Real-ESRGAN: Apache License 2.0
- FastAPI: MIT License
- React: MIT License
- TailwindCSS: MIT License

---

## 支持和联系

- **文档中心**：[docs/](./docs/)
- **API文档**：http://localhost:8000/docs (开发环境)
- **问题反馈**：GitHub Issues
- **功能请求**：GitHub Discussions
- **安全问题**：请发送邮件至 security@example.com

感谢您对 KBXY Monsters Pro 的关注和支持！