// client/src/components/TypeChartDialog.tsx
import React, { useEffect, useMemo, useState } from 'react'
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

type ChartDTO =
  | {
      base: string
      perspective: Perspective
      groups?: Partial<ChartGroups>
      all?: ChartGroupItem[]
      // 兜底字段（若服务端返回映射）
      attack_multipliers?: Record<string, number>
      defense_multipliers?: Record<string, number>
      mapping?: Record<string, number>
    }
  | Record<string, never>

const BTN_FX =
  'transition active:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300'

function formatMultiplier(n: number): string {
  // 期望样式：整数显示 1 位小数（×2.0），否则最多 3 位小数并去尾零
  if (Number.isInteger(n)) return `×${n.toFixed(1)}`
  const s = n.toFixed(3)
  return `×${s.replace(/0+$/, '').replace(/\.$/, '')}`
}

function normalizeChart(dto: ChartDTO): ChartGroups {
  // 1) 后端已分组的情况
  if (dto && 'groups' in dto && dto.groups) {
    return {
      high: dto.groups.high?.slice() || [],
      ordinary: dto.groups.ordinary?.slice() || [],
      low: dto.groups.low?.slice() || [],
    }
  }

  // 2) 后端给了全量数组
  if (dto && 'all' in dto && Array.isArray(dto.all)) {
    return splitToGroups(dto.all)
  }

  // 3) 后端给了映射：attack_multipliers / defense_multipliers / mapping
  const map =
    (dto && 'attack_multipliers' in dto && dto.attack_multipliers) ||
    (dto && 'defense_multipliers' in dto && dto.defense_multipliers) ||
    (dto && 'mapping' in dto && dto.mapping) ||
    null

  if (map && typeof map === 'object') {
    const arr: ChartGroupItem[] = Object.entries(map).map(([k, v]) => ({
      target: k,
      x: Number(v),
    }))
    return splitToGroups(arr)
  }

  // 4) 兜底空
  return { high: [], ordinary: [], low: [] }
}

function splitToGroups(arr: ChartGroupItem[]): ChartGroups {
  const high: ChartGroupItem[] = []
  const ordinary: ChartGroupItem[] = []
  const low: ChartGroupItem[] = []
  for (const it of arr) {
    const x = Number(it.x)
    if (Number.isFinite(x)) {
      if (Math.abs(x - 1) < 1e-9) ordinary.push(it)
      else if (x > 1) high.push(it)
      else low.push(it)
    }
  }
  // 排序：高→按倍率降序；低→倍率升序；普通→字典序
  high.sort((a, b) => b.x - a.x || a.target.localeCompare(b.target, 'zh'))
  low.sort((a, b) => a.x - b.x || a.target.localeCompare(b.target, 'zh'))
  ordinary.sort((a, b) => a.target.localeCompare(b.target, 'zh'))
  return { high, ordinary, low }
}

export default function TypeChartDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [perspective, setPerspective] = useState<Perspective>('attack')
  const [base, setBase] = useState<string>('')

  // Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 元素列表
  const elements = useQuery<string[]>({
    queryKey: ['type_elements'],
    enabled: open,
    queryFn: async () => {
      const r = await api.get('/api/v1/types/elements')
      const data = Array.isArray(r.data) ? r.data : r.data?.items || []
      return data as string[]
    },
    staleTime: 5 * 60 * 1000,
  })

  // 若第一次打开且 base 为空，自动选第一个元素
  useEffect(() => {
    if (!open) return
    if (!base && elements.data && elements.data.length > 0) {
      setBase(elements.data[0]!)
    }
  }, [open, base, elements.data])

  // 克制数据
  const chart = useQuery<ChartDTO>({
    queryKey: ['type_chart', perspective, base],
    enabled: open && !!base,
    queryFn: async () => {
      const r = await api.get('/api/v1/types/chart', {
        params: { perspective, base },
      })
      return r.data as ChartDTO
    },
    refetchOnWindowFocus: false,
  })

  const groups: ChartGroups = useMemo(() => normalizeChart(chart.data || {}), [chart.data])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="属性克制表"
      onClick={(e) => {
        // 点击遮罩关闭
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-[min(96vw,920px)] max-h-[88vh] overflow-hidden rounded-2xl bg-white shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="text-base font-semibold">属性克制表</div>
            <div className="text-xs text-gray-500">（仅显示倍率，不着色）</div>
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
        <div className="px-4 py-3 border-b bg-gray-50">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600 w-[5em]">视角</label>
              <select
                className="select"
                value={perspective}
                onChange={(e) => {
                  const p = (e.target.value as Perspective) || 'attack'
                  setPerspective(p)
                }}
              >
                <option value="attack">进攻视角（我打别人）</option>
                <option value="defense">防守视角（别人打我）</option>
              </select>
            </div>

            <div className="flex items-center gap-2 sm:col-span-2">
              <label className="text-sm text-gray-600 w-[5em]">基准元素</label>
              <select
                className="select"
                value={base}
                onChange={(e) => setBase(e.target.value)}
                disabled={elements.isLoading || !!elements.error}
              >
                {!elements.data?.length && <option value="">加载中或无数据</option>}
                {elements.data?.map((el) => (
                  <option key={el} value={el}>
                    {el}
                  </option>
                ))}
              </select>

              <div className="text-xs text-gray-500">
                {perspective === 'attack'
                  ? `当前：${base || '—'} → 其它元素`
                  : `当前：其它元素 → ${base || '—'}`}
              </div>
            </div>
          </div>
        </div>

        {/* 内容区 */}
        <div className="p-4 overflow-auto max-h-[calc(88vh-160px)]">
          {/* 加载/错误/空态 */}
          {chart.isLoading && (
            <div className="text-sm text-gray-500">加载克制数据...</div>
          )}
          {chart.error && (
            <div className="text-sm text-red-600">
              加载失败：{(chart.error as any)?.message || '未知错误'}
            </div>
          )}
          {!chart.isLoading && !chart.error && (
            <>
              {/* 高倍率 */}
              <Section
                title="高倍率（> ×1.0）"
                items={groups.high}
                placeholder="（无）"
              />
              {/* 普通 */}
              <Section
                title="普通（= ×1.0）"
                items={groups.ordinary}
                placeholder="（无）"
              />
              {/* 低倍率 */}
              <Section
                title="低倍率（< ×1.0）"
                items={groups.low}
                placeholder="（无）"
              />
            </>
          )}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
          <button className={`btn ${BTN_FX}`} onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
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
    <div className="mb-5">
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