// client/src/components/TypeChartDialog.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import api from '../api'

type Perspective = 'attack' | 'defense'

type ChartGroupItem = { target: string; x: number }
type ChartGroups = {
  high: ChartGroupItem[]
  ordinary: ChartGroupItem[]
  low: ChartGroupItem[]
}

// 兼容多种后端返回结构
type MatrixRows = Record<string, Record<string, number>>
type MatrixDTO =
  | {
      perspective?: Perspective
      types?: string[]
      matrix?: number[][]
      rows?: MatrixRows
      items?: Array<{ source: string; target: string; x: number }>
    }
  | Record<string, never>

const BTN_FX =
  'transition active:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300'

// ===== 固定排序表（按你的顺序） =====
const TYPE_ORDER = [
  '火系','金系','木系','水系','土系','翼系','怪系','魔系','妖系',
  '风系','毒系','雷系','幻系','冰系','灵系','机械系',
  '火风','木灵','圣系','土幻','水妖','音系'
]
const normalizeType = (s: string) => (s || '').replace(/\s+/g, '').replace(/系$/, '')
const TYPE_INDEX: Record<string, number> = TYPE_ORDER
  .map(normalizeType)
  .reduce((acc, t, i) => { acc[t] = i; return acc }, {} as Record<string, number>)

const compareByTypeOrder = (a: string, b: string) => {
  const na = normalizeType(a)
  const nb = normalizeType(b)
  const ia = Object.prototype.hasOwnProperty.call(TYPE_INDEX, na) ? TYPE_INDEX[na] : 999
  const ib = Object.prototype.hasOwnProperty.call(TYPE_INDEX, nb) ? TYPE_INDEX[nb] : 999
  if (ia !== ib) return ia - ib
  return a.localeCompare(b, 'zh')
}

const sortElementList = (arr: string[]) => arr.slice().sort(compareByTypeOrder)

// ========= 小工具 =========
async function getWithFallback<T = any>(primary: string, fallback: string, params?: any): Promise<T> {
  try {
    const r = await api.get(primary, { params })
    return r.data as T
  } catch {
    const r2 = await api.get(fallback, { params })
    return r2.data as T
  }
}

function formatMultiplier(n: number): string {
  if (!Number.isFinite(n)) return '×—'
  if (Math.abs(n - Math.round(n)) < 1e-12) return `×${n.toFixed(1)}`
  const s = n.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
  return `×${s}`
}

// 把多形态 MatrixDTO 统一成 rows 映射
function normalizeMatrix(dto: MatrixDTO): { types: string[]; rows: MatrixRows } {
  // 1) rows 已给
  if (dto && 'rows' in dto && dto.rows && typeof dto.rows === 'object') {
    const types = Object.keys(dto.rows)
    return { types, rows: dto.rows }
  }

  // 2) matrix + types
  if (dto && Array.isArray(dto.matrix) && Array.isArray(dto.types)) {
    const types = dto.types
    const rows: MatrixRows = {}
    dto.matrix.forEach((row, i) => {
      const from = types[i]
      rows[from] = rows[from] || {}
      row.forEach((val, j) => {
        const to = types[j]
        rows[from][to] = Number(val)
      })
    })
    return { types, rows }
  }

  // 3) items 扁平三元组
  if (dto && Array.isArray(dto.items)) {
    const rows: MatrixRows = {}
    const setTypes = new Set<string>()
    for (const it of dto.items) {
      if (!rows[it.source]) rows[it.source] = {}
      rows[it.source][it.target] = Number(it.x)
      setTypes.add(it.source); setTypes.add(it.target)
    }
    return { types: Array.from(setTypes), rows }
  }

  return { types: [], rows: {} }
}

// 从 rows 中抽取一行或一列并分组（分组内用固定顺序排序）
function pickGroups(rows: MatrixRows, types: string[], base: string, perspective: Perspective): ChartGroups {
  const arr: ChartGroupItem[] = []
  if (!base || !types.length) return { high: [], ordinary: [], low: [] }

  const orderedTypes = sortElementList(types)

  if (perspective === 'attack') {
    // 我打别人：取 base 行
    const row = rows[base] || {}
    for (const t of orderedTypes) {
      if (t === base) continue
      const x = Number(row[t])
      if (Number.isFinite(x)) arr.push({ target: t, x })
    }
  } else {
    // 别人打我：固定用“进攻矩阵”的列（即从 rows[from][base] 抽）
    for (const from of orderedTypes) {
      if (from === base) continue
      const x = Number(rows[from]?.[base])
      if (Number.isFinite(x)) arr.push({ target: from, x })
    }
  }

  return splitToGroups(arr)
}

function splitToGroups(arr: ChartGroupItem[]): ChartGroups {
  const high: ChartGroupItem[] = []
  const ordinary: ChartGroupItem[] = []
  const low: ChartGroupItem[] = []
  for (const it of arr) {
    const x = Number(it.x)
    if (!Number.isFinite(x)) continue
    if (Math.abs(x - 1) < 1e-9) ordinary.push(it)
    else if (x > 1) high.push(it)
    else low.push(it)
  }
  high.sort((a, b) => compareByTypeOrder(a.target, b.target))
  ordinary.sort((a, b) => compareByTypeOrder(a.target, b.target))
  low.sort((a, b) => compareByTypeOrder(a.target, b.target))
  return { high, ordinary, low }
}

// ========= 组件 =========
export default function TypeChartDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  // —— 与“一键匹配”完全一致的出入场策略：最短显示 1s + 500ms 柔和淡出 —— //
  const MIN_VISIBLE_MS = 1000
  const [mounted, setMounted] = useState(open)
  const [closing, setClosing] = useState(false)
  const shownAtRef = useRef<number>(0)

  useEffect(() => {
    if (open) {
      setMounted(true)
      shownAtRef.current = Date.now()
      const raf = requestAnimationFrame(() => setClosing(false))
      return () => cancelAnimationFrame(raf)
    } else if (mounted) {
      const since = Date.now() - (shownAtRef.current || Date.now())
      const wait = Math.max(0, MIN_VISIBLE_MS - since)
      const t1 = window.setTimeout(() => {
        setClosing(true)
        const t2 = window.setTimeout(() => setMounted(false), 500) // 与 duration-500 对齐
        return () => clearTimeout(t2)
      }, wait)
      return () => clearTimeout(t1)
    }
  }, [open, mounted])

  // Esc 关闭
  useEffect(() => {
    if (!mounted) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mounted, onClose])

  // 读取元素列表（后端：/types/list；兼容 /api/v1 前缀）
  const elements = useQuery<string[]>({
    queryKey: ['type_elements'],
    enabled: mounted,              // 仅挂载时拉取，避免闪烁
    queryFn: async () => {
      const data = await getWithFallback<any>('/api/v1/types/list', '/types/list')
      if (Array.isArray(data)) return data as string[]
      if (Array.isArray(data?.types)) return data.types as string[]
      if (Array.isArray(data?.items)) return data.items as string[]
      return []
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  // 排好序的元素列表
  const elementsSorted = useMemo(() => sortElementList(elements.data || []), [elements.data])

  // 选中的“基准元素”
  const [base, setBase] = useState<string>('')
  // 首次挂载或数据就绪时默认选择第一个
  useEffect(() => {
    if (!mounted) return
    if (!base && elementsSorted.length) setBase(elementsSorted[0]!)
  }, [mounted, base, elementsSorted])

  // 矩阵（仅拉“进攻视角”；“防守视角”用列读取）
  const matrix = useQuery<MatrixDTO>({
    queryKey: ['type_matrix', 'attack_only'],
    enabled: mounted,
    queryFn: async () =>
      await getWithFallback<MatrixDTO>('/api/v1/types/matrix', '/types/matrix', {
        perspective: 'attack',
      }),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 10 * 60 * 1000,
  })

  const { types, rows } = useMemo(() => normalizeMatrix(matrix.data || {}), [matrix.data])
  const allTypes = useMemo(() => sortElementList(types), [types])

  // 分组（同一份矩阵：行=攻，列=守）
  const groupsAttack: ChartGroups = useMemo(
    () => pickGroups(rows, allTypes, base, 'attack'),
    [rows, allTypes, base]
  )
  const groupsDefense: ChartGroups = useMemo(
    () => pickGroups(rows, allTypes, base, 'defense'),
    [rows, allTypes, base]
  )

  const isLoading = (elements.isLoading || matrix.isLoading) && mounted
  const hasError = !!(elements.error || matrix.error)
  const errorMsg = (elements.error as any)?.message || (matrix.error as any)?.message

  if (!mounted) return null

  return ReactDOM.createPortal(
    <div
      className={`fixed inset-0 z-50 backdrop-blur-sm bg-black/20 flex items-center justify-center
                  transition-opacity duration-500 ${closing ? 'opacity-0' : 'opacity-100'}`}
      role="dialog"
      aria-modal="true"
      aria-label="属性克制表"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className={`w-[min(96vw,1080px)] max-h-[88vh] overflow-hidden rounded-2xl bg-white shadow-xl
                    transition-all duration-500 ${closing ? 'opacity-0 scale-95' : 'opacity-100 scale-100'}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="text-base font-semibold">属性克制表</div>
            <div className="text-xs text-gray-500">（同一矩阵双视角：行=我打别人，列=别人打我）</div>
          </div>
          <button
            className={`btn h-8 px-2 ${BTN_FX}`}
            onClick={onClose}
            aria-label="关闭"
            title="关闭"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 控件区 */}
        <div className="px-5 py-3 border-b bg-gray-50">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600">基准元素</label>
              <select
                className="select"
                value={base}
                onChange={(e) => setBase(e.target.value)}
                disabled={elements.isLoading || !!elements.error}
              >
                {!elementsSorted.length && <option value="">加载中或无数据</option>}
                {elementsSorted.map((el) => (
                  <option key={el} value={el}>
                    {el}
                  </option>
                ))}
              </select>
            </div>

            <div className="text-xs text-gray-500">
              <span className="mr-3">×1.0 = 正常</span>
              <span className="mr-3">×&gt;1 = 加成</span>
              <span>×&lt;1 = 减免</span>
            </div>
          </div>
        </div>

        {/* 内容区 */}
        <div className="p-5 overflow-auto max-h-[calc(88vh-170px)]">
          {isLoading && <div className="text-sm text-gray-500">加载克制数据...</div>}

          {hasError && (
            <div className="text-sm text-red-600">加载失败：{errorMsg || '未知错误'}</div>
          )}

          {!isLoading && !hasError && (
            <div className="grid gap-5 md:grid-cols-2">
              {/* 进攻视角卡片 */}
              <div className="rounded-xl border bg-white">
                <div className="border-b px-4 py-3">
                  <div className="text-sm font-semibold">进攻视角（我打别人）</div>
                  <div className="text-xs text-gray-500">当前：{base || '—'} → 其它元素</div>
                </div>
                <div className="p-4">
                  <Section title="高倍率（> ×1.0）" items={groupsAttack.high} placeholder="（无）" />
                  <Section title="普通（= ×1.0）" items={groupsAttack.ordinary} placeholder="（无）" />
                  <Section title="低倍率（< ×1.0）" items={groupsAttack.low} placeholder="（无）" />
                </div>
              </div>

              {/* 防守视角卡片 */}
              <div className="rounded-xl border bg-white">
                <div className="border-b px-4 py-3">
                  <div className="text-sm font-semibold">防守视角（别人打我）</div>
                  <div className="text-xs text-gray-500">当前：其它元素 → {base || '—'}</div>
                </div>
                <div className="p-4">
                  <Section title="高倍率（> ×1.0）" items={groupsDefense.high} placeholder="（无）" />
                  <Section title="普通（= ×1.0）" items={groupsDefense.ordinary} placeholder="（无）" />
                  <Section title="低倍率（< ×1.0）" items={groupsDefense.low} placeholder="（无）" />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-end gap-2 border-t px-5 py-3">
          <button className={`btn ${BTN_FX}`} onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}

function Section({
  title,
  items,
  placeholder = '（无）',
}: {
  title: string
  items: ChartGroupItem[]
  placeholder?: string
}) {
  return (
    <div className="mb-4">
      <div className="mb-2 text-sm font-semibold text-gray-700">{title}</div>
      {items.length === 0 ? (
        <div className="text-xs text-gray-400">{placeholder}</div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map((it) => (
            <span
              key={it.target}
              className="badge whitespace-nowrap"
              title={`${it.target} ${formatMultiplier(it.x)}`}
            >
              {it.target}（{formatMultiplier(it.x)}）
            </span>
          ))}
        </div>
      )}
    </div>
  )
}