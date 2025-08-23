下面是**更新后的《kbxy-monsters-pro · 前端开发文档（Standalone）》**，已把你最近的改动同步进去（尤其是：**“识别文本”改为“识别链接（单页爬取）”**、三类标签体系、技能卡片 element/kind/power/description、仓库/可获得筛选、修复妖怪筛选、AI 打标签进度弹层、全站爬取按钮、派生批量等）。直接保存为 `docs/kbxy-frontend-dev-guide.md` 覆盖即可。

---

# kbxy-monsters-pro · 前端开发文档（Standalone）

> 一站式说明：技术栈、目录结构、环境、接口约定、两行工具栏、侧边栏就地编辑、批量操作、导出/备份恢复、**识别链接**、性能与自测。  
> **本文对应当前实现：Vite + React + TS + React Query + Tailwind。**

---

## 1) 技术栈与约束

- **构建**：Vite 5 + TypeScript 5  
- **数据**：Axios + React Query（缓存、重试、失效）  
- **样式**：Tailwind（本地构建）  
- **路由**：`react-router-dom@6`  
- **默认 API**：`http://localhost:8000`（可用 `VITE_API_BASE` 覆盖）  
- **浏览器**：现代浏览器（ES2020）

---

## 2) 目录结构（client/）

```
client/
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  postcss.config.cjs
  tailwind.config.ts
  src/
    api.ts                     # Axios 实例（baseURL、下载封装）
    styles.css                 # Tailwind 入口 + 基础样式
    main.tsx                   # App 入口，QueryClientProvider
    App.tsx                    # 页面骨架（TopBar + 路由）
    components/
      SideDrawer.tsx           # 右侧抽屉容器
      Pagination.tsx
      SkeletonRows.tsx
      Toast.tsx                # 轻提示（可选）
      ErrorBoundary.tsx
    pages/
      MonstersPage.tsx         # 列表/筛选/批量/抽屉编辑/识别链接/爬取/AI打标/派生
    types.ts                   # 轻量手写类型（Monster/TagCount/分页等）
```

---

## 3) 环境与命令

```bash
cd client
npm i
npm run dev       # http://localhost:5173
npm run build     # 产物 dist/
npm run preview   # 预览 dist/
```

**自定义后端地址**

```bash
VITE_API_BASE=http://127.0.0.1:8000 npm run dev
```

`src/api.ts` 会优先读取 `import.meta.env.VITE_API_BASE`。

---

## 4) 与后端的接口对齐（当前页面实际用到）

读取/聚合
- `GET /tags/i18n` → 标签 i18n（无则回退 `GET /tags/catalog`）
- `GET /tags?with_counts=true` → 仅展示 `buf_* / deb_* / util_*`
- `GET /roles` → 定位聚合
- `GET /stats` → 总数
- `GET /warehouse?page=1&page_size=1` → 严格以返回的 `total` 为仓库数量
- `GET /monsters` → 列表（支持 q/element/role/获取途径/new_type/tags_all/sort/order/page）

详情/技能/派生
- `GET /monsters/{id}`
- `GET /monsters/{id}/skills`
- `PUT /monsters/{id}/skills`（**裸数组**：`[{name, element?, kind?, power?, description?}]`）
- `GET /monsters/{id}/derived` → 角色建议 / 标签建议（抽屉里“一键匹配（填充）”）

创建/更新/删除/批量
- `POST /monsters`、`PUT /monsters/{id}`、`DELETE /monsters/{id}`
- `DELETE /monsters/bulk_delete`（失败回退 `POST /monsters/bulk_delete`）
- `POST /warehouse/bulk_set`（加入/移出仓库）

导入导出备份
- `GET /export/monsters.csv`（尊重当前筛选）
- `GET /backup/export_json`
- `POST /backup/restore_json`

AI/派生/兜底
- `POST /tags/monsters/{id}/retag_ai`（失败回退 `POST /tags/monsters/{id}/retag`）
- `POST /api/v1/derived/batch`（失败回退 `POST /derived/batch`）
- `POST /monsters/auto_match`（失败回退为逐条 `retag` + `derived`）

**爬虫（识别链接 & 一键全站）**
- `POST /api/v1/crawl/fetch_one` `{"url": "<详情页>"}`（也支持 `GET ?url=`）
- `POST /api/v1/crawl/crawl_all` `{"limit": N?}`

> 提示  
> 1) 创建如遇 `UNIQUE constraint failed: monsters.name`，按 409 视角处理成“重名已存在”；用户可改名或改为更新流程。  
> 2) `/api/v1/monsters` 并未公开（历史别名），统一走 `/monsters`。

---

## 5) 页面与交互（MonstersPage）

### 5.1 顶部工具栏（两段）

- 左侧：**导入 CSV** / **导出 CSV** / **备份 JSON** / **恢复 JSON**
- 右侧：  
  - **修复妖怪**：筛选当前页中“技能数为 0 或 >5”的项（会调用每条 `/monsters/{id}/skills` 统计）  
  - **一键 AI 打标签**：逐条调用 `retag_ai`（带真实进度弹层）  
  - **一键全部派生**：调用批量派生接口（失败则逐条 `GET /monsters/{id}/derived`）  
  - **仓库管理**（仅看 possess=true）  
  - **仅显示可获得妖怪**（new_type=true）  
  - **一键爬取图鉴**：触发 `/api/v1/crawl/crawl_all`（可选 limit）  
  - **新增妖怪**：打开抽屉进入创建态

### 5.2 搜索与上限（两列）

- 左：关键词搜索（名称 / 技能关键词）
- 右：**抓取上限**（一键全站爬取用的 limit 数字框）

### 5.3 第二排筛选（7 列）

- 元素（中文）  
- 获取途径（“可捕捉宠物 / BOSS宠物 / 活动获取宠物 / 兑换/商店 / 任务获取 / 超进化 / 其它”）
- 三个标签下拉：🟢buf / 🔴deb / 🟣util（只认新前缀）  
- 定位（从 `/roles` 读取）  
- 排序键 + 升降序（`updated_at/offense/survive/control/tempo/pp_pressure`）

> 标签文案通过 `GET /tags/i18n` 渲染；无接口时回退原代号。

### 5.4 统计卡片

- **仓库妖怪数量**：来自 `/warehouse` 的 `total`  
- **总数**：`/stats.total`

### 5.5 列表与批量

- 行勾选（首列复选框）→ 顶部出现批量条：清除选择 / 加入仓库 / 移出仓库 / 批量删除  
- 名称列点击 → 打开**右侧抽屉**

---

## 6) 右侧抽屉 · 详情 / 编辑

### 6.1 展示态

- 顶部状态徽章：可获取（new_type）/ 暂不可 / 已拥有（possess）  
- 获取渠道（type）与获取方式（method）；创建/更新时间  
- **基础种族值（六维）**：hp/speed/attack/defense/magic/resist + 总和  
- **技能列表**：显示 `name` 与右上角 `element/kind/power`，下方是 description（有才展示）  
- **标签**：按 🟢/🔴/🟣 三块展示

### 6.2 编辑态（就地编辑）

- **基础信息**：名称 / 元素 / 定位 / possess / new_type / 渠道 type / 获取方式 method / 三类标签（仅允许 `buf_*|deb_*|util_*`）  
- **六维**：滑条 + 数值框，实时显示总和  
- **技能**：**卡片编辑**（多行），字段：`name | element | kind | power | description`  
  - 保存时，先 `PUT /monsters/{id}` 再 `PUT /monsters/{id}/skills`（裸数组）  
  - `power` 数值自动清洗：空 → `null`；非数 → 忽略；0 可用  
  - `element`/`kind` 字段保持与后端规范一致（“特殊”不当元素；`kind` 取“物理/法术/特殊”）

### 6.3 “识别链接”（替代旧“识别文本”）

- 抽屉“识别粘贴框”**已改为识别链接**：  
  - **输入**：单个 4399 图鉴详情页 URL  
  - **点击**：`识别并填充` → 调用 `/api/v1/crawl/fetch_one`  
  - **回填**：名称、六维、元素、获取渠道/方式、以及一组 **规范化后的技能**（element/kind/power/desc）  
  - 如遇已存在的重名，仍可在编辑态修改后“保存”（**创建新建**会因唯一键失败，此时请改名或返回编辑已有记录）  
- 一键匹配（填充）：从 `/monsters/{id}/derived` 读取 `role_suggested` 与建议标签（自动过滤成新前缀三类）

---

## 7) 一键操作与真实进度

- **AI 打标签**：  
  逐条调用 `POST /tags/monsters/{id}/retag_ai`（失败回退到 `/retag`），  
  弹层显示实时进度：总数/已完成/成功/失败 + 百分比。
- **一键全部派生**：  
  `POST /api/v1/derived/batch`（失败退回 `/derived/batch` 或逐条 `GET /monsters/{id}/derived`）。  
- **一键爬取图鉴**：  
  `POST /api/v1/crawl/crawl_all`，可选 `limit`；完成后刷新列表/统计，并在抽屉内刷新当前选中项。

---

## 8) 导入 / 导出 / 备份 / 恢复

- **导入 CSV**：后端已提供导入路由；前端入口放在工具栏左侧  
- **导出 CSV**：`GET /export/monsters.csv`（携带当前筛选）  
- **备份 JSON**：`GET /backup/export_json`  
- **恢复 JSON**：`POST /backup/restore_json`（传入导出的结构即可）

---

## 9) 本地化与标签体系

- 只认三类前缀：`buf_*`（增强）/ `deb_*`（削弱）/ `util_*`（特殊）。  
- 文案优先用 `/tags/i18n`，退化到代号直出。  
- 列表单元格每类最多展示 3 个徽章（其余省略）。

---

## 10) 错误处理与可用性

- 所有请求都带错误兜底：弹 toast/alert，并在控制台打印（含 `x-trace-id`）。  
- **创建重名**：提示“名称已存在”，建议用户改名或转为编辑已有。  
- **DELETE 带 body 被代理拦截**：自动回退 `POST /monsters/bulk_delete`。  
- **/api/v1/monsters 404**：统一使用 `/monsters`。  
- **爬取识别失败**：提示“无法从该链接识别数据”，保留用户已填内容。

---

## 11) 性能与交互细节

- React Query：  
  - 列表默认 `staleTime` 合理设置（例如数秒），避免反复抖动。  
  - 批量/保存后精确失效：`['monsters', params]`、`['stats']`、`['warehouse_stats_total_only']`、当前选中项的 `['skills', id]`。  
- 大量批量操作时，进度弹层采用**确定进度**（有总数）或**未知进度**两种样式。  
- 列表骨架使用 `SkeletonRows`；空态提供“调整筛选/导入 JSON/CSV”的引导。

---

## 12) 自测清单（前端）

- [ ] 顶部工具栏：导入/导出/备份/恢复可用  
- [ ] 搜索与分页正常；ETag 显示随列表更新  
- [ ] 元素/获取途径/三类标签/定位/排序/方向 → 正确生效  
- [ ] **修复妖怪**：能筛出“技能 0 或 >5”的项  
- [ ] **仓库管理**与**仅显示可获得妖怪**切换正常  
- [ ] 行勾选 + 批量：加入/移出仓库、批量删除正常  
- [ ] 抽屉展示完整：六维/技能/标签/获取方式  
- [ ] **编辑态**保存（基础 + 技能卡片）正常  
- [ ] **识别链接**：贴入 4399 详情页 URL → 正确回填（名称/六维/元素/渠道/技能）  
- [ ] 一键匹配（填充）：能把建议角色/标签写入编辑表单  
- [ ] **AI 打标签**：进度数字与结果吻合  
- [ ] **一键全部派生**：完成后派生指标列更新  
- [ ] **一键爬取图鉴**：能返回“遍历/新增/更新/技能变更”统计并刷新页面  
- [ ] 导出/备份/恢复：文件结构正确，可往返闭环

---

## 13) 常见问题（FAQ）

**Q：识别链接需要什么格式？**  
A：直接粘贴 4399 图鉴**详情页** URL（如 `https://news.4399.com/kabuxiyou/.../xxxx.html`）；点击“识别并填充”后端会返回规范化字段。

**Q：识别后保存失败显示“名称已存在”？**  
A：后端 `monsters.name` 唯一。识别出的名称与现有记录重名时，请改名，或取消创建去编辑已存在的那条。

**Q：技能元素/类型为什么有时是“特殊”？**  
A：后端把“特/无/状态/辅助”等统一归到“特殊”；`kind` 只认“物理/法术/特殊”。

**Q：/tags 文案是英文代号？**  
A：`/tags/i18n` 不可用时会退化为代号直出。你可以在后端补上 i18n。

---

**文档版本**：2025-08-15（已同步“识别链接”与一键爬取/AI 打标/派生/三类标签等前端行为）  
需要我把**识别链接**的实现细节补一份“前端改动清单（diff 指南）”吗？我可以把涉及的状态、handler、API 调用与占位文案一并列出来。