# kbxy-monsters-pro · 前端开发文档（Standalone）

> 一站式说明：技术栈、目录结构、环境、接口约定、导入向导、侧边栏编辑、批量操作、导出/备份恢复、错误边界、性能与自测。文档针对当前实现（Vite + React + TS + React Query + RHF + Zod + Tailwind），并覆盖近期新增改动：**两行工具栏（标签/定位 + 排序/方向）**、**侧边栏就地编辑**、**批量勾选与删除**、**CSV 导出**、**备份/恢复**、**技能多条描述**、**智能识别（技能+六维）入口**等。

---

## 1. 技术栈与约束

- **构建**：Vite 5 + TypeScript 5  
- **UI**：Tailwind（本地构建，禁止 CDN 版）  
- **数据**：Axios + React Query（缓存、重试、失效、并发去重）  
- **表单**：React Hook Form + Zod（schema 校验）  
- **路由**：`react-router-dom@6`  
- **接口默认域名**：`http://localhost:8000`（可用 `VITE_API_BASE` 覆盖）  
- **浏览器**：现代浏览器（ES2020）

---

## 2. 目录结构（client/）

```
client/
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  postcss.config.cjs
  tailwind.config.ts
  src/
    api.ts                      # Axios 实例（baseURL、拦截器、下载辅助）
    styles.css                  # Tailwind 入口 + 基础样式
    main.tsx                    # App 入口，QueryClientProvider
    App.tsx                     # 页面骨架（TopBar + 路由）
    pages/
      MonstersPage.tsx          # 首页列表、两行工具栏、侧边栏、批量操作
      AddMonsterDrawer.tsx      # 新增/编辑抽屉（就地编辑）
      ImportDialog.tsx          # 导入向导（上传→预览→提交）
    components/
      TopBar.tsx                # 顶部条：健康状态、导入、GitHub、刷新
      ToolbarChips.tsx          # 两行工具栏（行1：标签/定位；行2：排序/方向）
      StatsBar.tsx              # 统计卡片（/stats）
      BulkActionsBar.tsx        # 勾选计数、批量删除、导出、备份/恢复
      SideDrawer.tsx            # 右侧抽屉
      SkillEditor.tsx           # 技能列表编辑（多条 + 描述）
      Checkbox.tsx              # 行勾选
      Pagination.tsx            # 分页
      SkeletonRows.tsx          # 表格骨架
      ErrorBoundary.tsx         # 错误边界
      Toast.tsx                 # 轻提示
      ConfirmDialog.tsx         # 确认弹窗
    hooks/                      # （可选）自定义 hooks（useMonsters/useStats 等）
    types/                      # OpenAPI/手写类型
```

---

## 3. 环境与命令

```bash
cd client
npm i
npm run dev       # http://localhost:5173
npm run build     # 产物 dist/
npm run preview   # 预览 dist/
```

**可配置 API 地址**
```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```
`src/api.ts` 会优先读取 `import.meta.env.VITE_API_BASE`。

---

## 4. API 访问与类型

### 4.1 Axios 实例（`src/api.ts`）

- 基础：
  - `baseURL = VITE_API_BASE || 'http://localhost:8000'`
  - 超时 10s
  - 响应拦截器：读取 `x-trace-id`，错误透传
- 下载辅助：
  - `api.download(url, params)`：封装 `blob` 下载（CSV/JSON）

### 4.2 OpenAPI 类型（推荐）

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.d.ts
```

在页面与组件中引用生成类型，尽量避免 `any`。

---

## 5. 关键接口对齐（与后端）

- `GET /health`：健康状态（TopBar 显示 “API OK · n”）
- `GET /monsters`：列表（q/element/role/tag/sort/order/page/page_size）
- `GET /monsters/{id}`
- `POST /monsters`、`PUT /monsters/{id}`、`DELETE /monsters/{id}`
- `GET /monsters/{id}/skills` · `PUT /monsters/{id}/skills`（覆盖技能集合：`[{name, description}]`）
- `GET /tags?with_counts=true`：标签聚合
- `GET /roles`：定位聚合
- `GET /stats`：统计（total / with_skills / tags_total）
- `GET /export/monsters.csv`：导出（尊重筛选）
- `GET /backup/export_json`：备份 JSON
- `POST /backup/restore_json`：恢复 JSON（上送导出的结构即可）
- `DELETE /monsters/bulk_delete`（或 `POST` 同路径，兼容不支持 DELETE body 的代理）

> 若 `/stats` 或导出/备份 404，请确认后端 `app.include_router(backup.router)` 已挂载。

---

## 6. 页面与交互

### 6.1 两行工具栏（极简中性）

- **第 1 行**：标签（多选 Chip） · 定位（下拉）  
- **第 2 行**：排序（select：更新时间/名称/攻/生/控/速/PP） · 方向（升/降）  
- **搜索**：仍保留输入框，但压缩宽度（不抢占布局），支持 `Enter` 提交与 300ms debounce。

### 6.2 列表 + 勾选 + 批量操作

- 行首 `Checkbox` 进入勾选模式；顶部显示 `已选 N 项` + 按钮：
  - **批量删除**：调用 `/monsters/bulk_delete`（默认 `DELETE`，失败则自动回退 `POST` 同路径）
  - **导出 CSV**：调用 `/export/monsters.csv`（带当前筛选参数）
  - **备份 JSON**：调用 `/backup/export_json`
  - **恢复 JSON**：弹窗选择文件 → `/backup/restore_json`
- 删除采用确认对话框；成功后 `invalidateQueries(['monsters','stats'])`

### 6.3 侧边栏（就地编辑）

- 点击“名称”打开 `SideDrawer`
  - 上部：**智能识别卡片**（若启用）：展示识别出的技能/六维（只显示，不写库）
  - 大块：**基础种族值（六维）** 独立分栏，显示 `raw_stats`；总和置底
  - **技能**：多条 + 描述；支持就地编辑、增删行，保存时 `PUT /monsters/{id}/skills`
  - **标签**：Chip 展示（不编辑）
  - 顶部操作按钮：编辑（切换到 `AddMonsterDrawer` 或内嵌表单）、删除（单条）

### 6.4 新增/编辑抽屉（`AddMonsterDrawer.tsx`）

- 表单字段：
  - 基础：`name_final`（必填）、`element`、`role`、`tags`
  - 六维：`hp / speed / attack / defense / magic / resist`（Zod 数值校验）
  - 技能（可选）：动态列表 `[{name, description}]`
- 发送：
  - 新增：`POST /monsters` +（若带技能）再 `PUT /monsters/{id}/skills`
  - 编辑：`PUT /monsters/{id}` + 选择是否覆盖技能（开关）
- 保存成功：toast · 关闭抽屉 · 列表与统计失效

---

## 7. 导入向导

- **上传 → 预览 → 提交**
  - 预览：显示列、总行数、样例 10 行、提示（缺列等）
  - 提交：带 `Idempotency-Key`（`crypto.randomUUID()`），回显 “插入/更新/跳过/错误”
  - 成功后刷新列表与统计；保留最近一次结果（快照）

**文件要点**（与后端一致）

- UTF-8，分隔符自动识别（`,`/`\t`/`;`/`|`）
- 标签支持 `| , ; 空白`
- 技能名称列：`技能|关键技能|skill[1..]`；描述列：`*_desc` 或邻近 3 列中符合描述语义的文本  
- 主观“评价/总结”列仅展示在侧边栏“评价 / 总结”，**不**当作技能描述

---

## 8. 表单与校验

- 使用 Zod：
  - `name_final`: `z.string().min(1)`
  - 六维：`z.coerce.number().min(0).max(300)`
  - 技能：`z.array(z.object({ name: z.string().min(1), description: z.string().optional() }))`
- RHF：
  - 错误提示与禁用提交
  - 保存中按钮 loading 态
  - 取消确认提示（表单脏）

---

## 9. 错误边界与诊断

- **ErrorBoundary**：捕获渲染期异常
- **请求期**：React Query `onError` → toast，同时在控制台输出 `trace_id`
- 空/错/加载三态：Skeleton / 空状态（含“清空筛选/去导入”） / 错误卡片（可复制 `trace_id`）

---

## 10. 性能要点

- `staleTime` 合理设置（例如列表 5s），减少抖动
- 批量操作完成后，精准失效：`['monsters']`、`['stats']`
- 长列表（>1000）再考虑虚拟滚动
- 组件拆分与 `React.memo`，避免抽屉更新导致整表重渲

---

## 11. 打包与部署

```bash
npm run build    # 产物 dist/
```

- 静态托管（Nginx/Caddy 等）
- 后端可同域挂 `/api`，或前端以 `VITE_API_BASE` 指向后端域名
- 建议设置缓存策略与 gzip/br

---

## 12. 自测清单

- [ ] 顶部状态显示 “API OK · n”，无控制台报错  
- [ ] 工具栏：标签/定位/排序/方向 能正确筛选  
- [ ] 搜索：回车触发，带 debounce  
- [ ] 侧边栏：六维、技能（多条+描述）、评价可见；**就地编辑技能**可保存  
- [ ] 新增/编辑抽屉：字段校验、保存成功刷新  
- [ ] 勾选 + 批量删除：确认后删除成功，统计更新  
- [ ] 导出 CSV：文件内容正确、包含当前筛选  
- [ ] 备份 JSON/恢复：结构匹配、恢复后数据一致  
- [ ] 导入向导：预览→提交→回显结果，列表更新  
- [ ] 错误态：复制 `trace_id` 可用于后端日志定位

---

## 13. 常见问题（FAQ）

- **/stats 或导出/备份 404？**  
  后端需 `app.include_router(backup.router)`。已包含则检查路径：导出 CSV 为 **`/export/monsters.csv`**。
- **批量删除 422？**  
  前端需 `Content-Type: application/json` 且 body 为 `{"ids":[...]}`。部分代理不支持 DELETE body，可自动退回 `POST /monsters/bulk_delete`。
- **备份导出 500（SQLAlchemy unique）？**  
  后端使用 `selectinload`（已修），或在 `joinedload` 时 `.unique().scalars().all()`。
- **技能描述丢失/错误？**  
  确认 CSV 使用 `*_desc` 或描述列在技能名右侧 3 列内；主观总结列不会当作技能描述入库。

---

**文档版本**：2025-08-12 · 匹配当前前端实现（两行工具栏 / 侧边栏就地编辑 / 批量操作 / 导出备份）  
需要我顺手把这份文档落到仓库里并建立侧边目录（`docs/README.md` 索引）吗？