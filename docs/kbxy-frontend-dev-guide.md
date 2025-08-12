# kbxy-monsters-pro · 前端开发文档（Standalone）

> 目标：提供**前端开发与联调**的一站式说明；覆盖技术栈、目录结构、环境与命令、接口约定、表单与校验、错误边界、导入向导、状态与性能、打包与部署、自测清单。文档针对当前仓库 `client/` 的实现：Vite + React + TypeScript + React Query + React Hook Form + Zod + Tailwind（本地构建）。

---

## 1. 技术栈与约束

- **构建**：Vite 5 + TypeScript 5
- **UI**：原子化样式 Tailwind（本地构建，**禁止使用 CDN 版**）
- **数据**：Axios + React Query（请求缓存、重试、失效、并发去重）
- **表单**：React Hook Form（RHF）+ Zod（schema 校验）
- **状态**：以 React Query 为主，局部 `useState` 为辅；避免全局状态库
- **接口域名**：默认 `http://localhost:8000`（见 `src/api.ts`）
- **浏览器支持**：现代浏览器（ES2020）

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
    api.ts                 # Axios 实例（baseURL、超时、拦截器）
    styles.css             # Tailwind 入口 + 基础样式
    main.tsx               # 应用入口，挂载 QueryClientProvider
    App.tsx                # 首页列表 + 导入按钮
    components/
      ImportDialog.tsx     # 导入向导（上传 -> 预览 -> 提交）
    types/                 # （建议）放 TS 类型与 OpenAPI 生成文件
    hooks/                 # （建议）放自定义 hooks（useMonsters 等）
    pages/                 # （建议）按路由拆分页面
```

> 若后续引入路由，推荐 `react-router-dom@6`，但当前示例未使用。

---

## 3. 环境与命令

```bash
cd client
npm i
npm run dev       # 开发，默认 http://localhost:5173
npm run build     # 打包产物输出到 dist/
npm run preview   # 预览 dist/
```

**常见问题**
- 白屏：打开浏览器控制台检查网络请求是否跨域失败，或检查是否误用了 tailwind CDN；本项目已配置本地 Tailwind。  
- CORS：确保后端允许 `http://localhost:5173`（见 `server/app/config.py` 的 `cors_origins`）。

---

## 4. API 访问与类型

### 4.1 Axios 基础实例（`src/api.ts`）
```ts
import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 10000,
})

// （可选）响应拦截器：读取 x-trace-id，错误透传
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const traceId = err?.response?.headers?.['x-trace-id']
    if (traceId) console.warn('trace_id:', traceId)
    return Promise.reject(err)
  }
)

export default api
```

### 4.2 与后端强类型对齐（推荐）
- 访问 `http://localhost:8000/openapi.json`，使用 `openapi-typescript` 生成 TS 类型：
```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.d.ts
```
- 在代码中引用 `paths["/monsters"]["get"]["responses"]["200"]["content"]["application/json"]` 等类型，避免 `any`。

---

## 5. 数据获取与缓存（React Query）

**模式**
- 一个 API = 一个 `useQuery` / `useMutation`；
- `queryKey` 精确描述参数；
- 列表与详情分离；列表更新后可选择性 `invalidateQueries`。

**示例（列表）**
```ts
import { useQuery } from '@tanstack/react-query'
import api from '@/api'

export function useMonsters(params: { q?: string }) {
  return useQuery({
    queryKey: ['monsters', params],
    queryFn: async () => (await api.get('/monsters', { params })).data,
    staleTime: 5 * 1000,
    retry: 2,
  })
}
```

**示例（提交导入）**
```ts
import { useMutation, useQueryClient } from '@tanstack/react-query'

export function useCommitImport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return (await api.post('/import/commit', fd, {
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })).data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['monsters'] }),
  })
}
```

---

## 6. 表单与校验（RHF + Zod）

**基本写法**
```ts
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'

const schema = z.object({
  name_final: z.string().min(1, '必填'),
  element: z.string().optional(),
  base_offense: z.coerce.number().min(0).max(300),
})

type FormValues = z.infer<typeof schema>

// 组件内：
const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({ resolver: zodResolver(schema) })
```

**提示**
- 用 `z.coerce.number()` 处理输入框的字符串转数值；
- 后端也会再做 Pydantic 校验，形成“前后端双重校验”。

---

## 7. 错误处理与 UI 三态

**全局 Error Boundary**
- 顶层放置 `ErrorBoundary`，捕获渲染期异常并展示兜底 UI；
- 请求期错误通过 React Query 的 `onError` 统一 toast + 诊断面板；

**三态骨架（Loading/Empty/Error）**
- 列表页与详情页均需实现：
  - Loading：骨架组件/Skeleton；
  - Empty：空状态提示与“清空筛选/去导入”行动按钮；
  - Error：展示 `message` + 可展开 `trace_id`。

**从响应头透传 trace_id**
- `err.response.headers['x-trace-id']` → 诊断面板可复制；
- 与后端日志对齐问题定位。

---

## 8. 导入向导（上传 → 预览 → 提交）

**交互要点**
1. 选择文件后先调用 `/import/preview`，展示：列名、总行数、样例 10 行、提示（缺列等）；
2. 提交调用 `/import/commit`，附带 `Idempotency-Key`，显示插入/更新/跳过/错误列表；
3. 成功后刷新列表，并保留最后一次导入结果状态；
4. 支持 `, | ; 空白` 多分隔符的标签拆分提示（与后端一致）。

**样式建议**
- 对于错误行，表格内标红具体列；
- 大文件上传过程中提供进度与可取消（可后续扩展为分片/断点）。

---

## 9. 性能与可访问性

- React Query 合理设置 `staleTime`、`gcTime`，避免列表频繁抖动；
- 列表使用虚拟滚动（当 > 1000 行再考虑）；
- 控件加 `aria-*` 属性与 `label`，保证键盘可用；
- 图片/图标懒加载，保持首屏渲染流畅。

---

## 10. 构建与部署

```bash
npm run build    # 产物: client/dist
```

**静态托管**
- Nginx/Caddy/Apache 任一静态服务即可；
- 若前后端同域，建议：
  - 前端：`https://example.com/`
  - 后端：反向代理同域 `/api`（或直接后端改 `root_path`），*或* 在前端把 `baseURL` 指向后端域名；

**环境区分**
- 建议在构建时注入 `VITE_API_BASE`：
```bash
VITE_API_BASE=https://api.example.com npm run build
```
- `src/api.ts`：
```ts
const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000' })
```

---

## 11. 代码风格与质量（建议）

- **格式化**：Prettier（可加脚本 `npm run fmt`）
- **Lint**：ESLint（typescript-eslint），规则：no-explicit-any、no-floating-promises 等
- **提交钩子**：husky + lint-staged（阻断不合规提交）
- **测试**（可选）：Vitest + @testing-library/react，覆盖 hooks 与组件交互

---

## 12. 自测清单（前端）

- [ ] 首页加载：看到 “API OK · …”，无控制台错误；
- [ ] 搜索：输入关键字能实时过滤；
- [ ] 导入：能预览→提交，返回 “插入/更新/跳过/错误”；
- [ ] 错误态：断网或 500 能显示错误卡片，能复制 `trace_id`；
- [ ] 详情：点击行（若实现）能进入详情；
- [ ] 打包：`npm run build` 成功，`npm run preview` 可访问。

---

## 13. 路线图（可选）

- 引入 `react-router-dom`，拆分「列表/详情/导入历史」路由；
- UI 组件库（shadcn/ui 或 HeadlessUI）与图表（Recharts）；
- 导入历史页：展示每次 Idempotency-Key 的结果；
- FTS5 搜索的前端联动（高亮匹配、前缀提示）；
- i18n（中文/英文）。

---

> 文档版本：2025-08-12 · 适配 `kbxy-monsters-pro` 现有前端实现
