// client/src/components/TypeChartDialog.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import ReactDOM from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import api from '../api'

type Perspective = 'attack' | 'defense'

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

  // 选中的"基准元素"
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
          <div className="flex items-center justify-center gap-4">
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
        <div className="p-3 overflow-auto max-h-[calc(88vh-100px)]">
          {isLoading && <div className="text-sm text-gray-500">加载克制数据...</div>}

          {hasError && (
            <div className="text-sm text-red-600">加载失败：{errorMsg || '未知错误'}</div>
          )}

          {!isLoading && !hasError && (
            <RadarChart
              base={base}
              rows={rows}
              allTypes={allTypes}
            />
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


function RadarChart({
  base,
  rows,
  allTypes,
}: {
  base: string
  rows: MatrixRows
  allTypes: string[]
}) {
  if (!base || !allTypes.length) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-500">
        请选择基准元素
      </div>
    )
  }

  // 响应式尺寸计算 - 适中尺寸
  const containerSize = Math.min(window.innerWidth * 0.88, window.innerHeight * 0.72, 650)
  const svgSize = containerSize
  const centerX = svgSize / 2
  const centerY = svgSize / 2
  const maxRadius = svgSize * 0.38
  const minRadius = svgSize * 0.15

  // 排除当前基准元素的其他属性
  const otherTypes = allTypes.filter(t => t !== base)
  const angleStep = (2 * Math.PI) / otherTypes.length

  // 计算每个属性的角度位置
  const typePositions = otherTypes.map((type, index) => {
    const angle = index * angleStep - Math.PI / 2 // 从顶部开始
    return { type, angle }
  })

  // 获取攻击和防守数据
  const attackData = typePositions.map(({ type, angle }) => {
    const multiplier = rows[base]?.[type] || 1
    const radius = minRadius + (maxRadius - minRadius) * Math.min(Math.max(multiplier - 0.5, 0) / 1.5, 1)
    return {
      type,
      angle,
      multiplier,
      radius,
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    }
  })

  const defenseData = typePositions.map(({ type, angle }) => {
    const multiplier = rows[type]?.[base] || 1
    const radius = minRadius + (maxRadius - minRadius) * Math.min(Math.max(multiplier - 0.5, 0) / 1.5, 1)
    return {
      type,
      angle,
      multiplier,
      radius,
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    }
  })

  // 根据倍率计算半径的函数
  const getRadiusForMultiplier = (multiplier: number) => {
    return minRadius + (maxRadius - minRadius) * Math.min(Math.max(multiplier - 0.5, 0) / 1.5, 1)
  }

  // 只保留重要的参考线
  const gridData = [
    { multiplier: 1.0, radius: getRadiusForMultiplier(1.0), important: true },
    { multiplier: 2.0, radius: getRadiusForMultiplier(2.0), important: true },
  ]

  return (
    <div className="flex flex-col items-center">
      <div className="relative flex justify-center">
        <svg width={svgSize} height={svgSize} className="overflow-visible">
          {/* 背景网格 - 简化版 */}
          <g>
            {/* 重要参考圈 (1.0x 和 2.0x) */}
            {gridData.map((grid, i) => (
              <g key={`grid-${i}`}>
                <circle
                  cx={centerX}
                  cy={centerY}
                  r={grid.radius}
                  fill="none"
                  stroke={grid.multiplier === 1.0 ? "#10b981" : "#ef4444"}
                  strokeWidth="1.5"
                  opacity="0.4"
                  strokeDasharray="4,4"
                />
                {/* 倍率标签 */}
                <text
                  x={centerX + grid.radius + svgSize * 0.02}
                  y={centerY + 3}
                  className="fill-gray-600 text-xs"
                >
                  ×{grid.multiplier}
                </text>
              </g>
            ))}
          </g>

          {/* 攻击视角雷达 */}
          <g>
            <polygon
              points={attackData.map(d => `${d.x},${d.y}`).join(' ')}
              fill="rgba(59,130,246,0.25)"
              stroke="#3b82f6"
              strokeWidth="2.5"
            />
            {attackData.map((d, i) => (
              <circle key={`attack-${i}`} cx={d.x} cy={d.y} r={svgSize * 0.01} fill="#3b82f6" />
            ))}
          </g>

          {/* 防守视角雷达 */}
          <g>
            <polygon
              points={defenseData.map(d => `${d.x},${d.y}`).join(' ')}
              fill="rgba(239,68,68,0.25)"
              stroke="#ef4444"
              strokeWidth="2.5"
            />
            {defenseData.map((d, i) => (
              <circle key={`defense-${i}`} cx={d.x} cy={d.y} r={svgSize * 0.01} fill="#ef4444" />
            ))}
          </g>

          {/* 中心点和基准元素 */}
          <circle cx={centerX} cy={centerY} r={svgSize * 0.02} fill="#6366f1" />
          <text
            x={centerX}
            y={centerY - svgSize * 0.05}
            textAnchor="middle"
            className="fill-gray-900 text-sm font-semibold"
          >
            {base}
          </text>

          {/* 属性标签 */}
          {typePositions.map(({ type, angle }, i) => {
            const labelRadius = maxRadius + svgSize * 0.08
            const labelX = centerX + labelRadius * Math.cos(angle)
            const labelY = centerY + labelRadius * Math.sin(angle)
            const attackMultiplier = attackData[i]?.multiplier || 1
            const defenseMultiplier = defenseData[i]?.multiplier || 1
            
            return (
              <g key={`label-${i}`}>
                <text
                  x={labelX}
                  y={labelY}
                  textAnchor="middle"
                  className="fill-gray-900 text-base font-medium"
                >
                  {type}
                </text>
                <text
                  x={labelX}
                  y={labelY + 12}
                  textAnchor="middle"
                  className="fill-blue-600 text-[10px]"
                >
                  攻:{formatMultiplier(attackMultiplier)}
                </text>
                <text
                  x={labelX}
                  y={labelY + 22}
                  textAnchor="middle"
                  className="fill-red-600 text-[10px]"
                >
                  守:{formatMultiplier(defenseMultiplier)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>

      {/* 图例 */}
      <div className="mt-2 space-y-1">
        <div className="flex gap-8 text-sm justify-center">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-blue-500 rounded-full"></div>
            <span>攻击视角（我打别人）</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-red-500 rounded-full"></div>
            <span>防守视角（别人打我）</span>
          </div>
        </div>
        <div className="flex gap-8 text-xs justify-center text-gray-600">
          <div className="flex items-center gap-2">
            <div className="w-3 h-px bg-green-600 border-dashed"></div>
            <span>×1.0参考线</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-px bg-red-600 border-dashed"></div>
            <span>×2.0参考线</span>
          </div>
        </div>
      </div>
    </div>
  )
}