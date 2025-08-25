// client/src/components/MonsterCardGrid.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { Monster } from '../types'

type Ribbon = { text: string; colorClass?: string } | null

type Props = {
  items: Monster[]
  selectedIds: Set<number>
  onToggleSelect: (id: number) => void
  onOpenDetail: (m: Monster) => void
  showRawSummary?: boolean
  getImageUrl?: (m: Monster) => string | null
  computeRibbon?: (m: Monster) => Ribbon
  /** 卡片最小宽度（更紧凑默认 160）& 图片高度（默认 clamp(110px, 18vw, 180px)） */
  minCardWidthPx?: number
  mediaHeightCss?: string
  className?: string
}

/* ===================== 模块级缓存（关键） ===================== */
const resolvedUrlCache = new Map<string, string | null>()
const resolvingCache = new Map<string, Promise<string | null>>()

const BLOB_LIMIT_DEFAULT = 300
let BLOB_LIMIT = BLOB_LIMIT_DEFAULT
const blobLRU = new Map<string, string>() // key=原始URL，value=blob:URL
function blobGet(url: string) {
  const v = blobLRU.get(url)
  if (v) { blobLRU.delete(url); blobLRU.set(url, v) }
  return v || null
}
function blobSet(url: string, objUrl: string) {
  if (blobLRU.has(url)) blobLRU.delete(url)
  blobLRU.set(url, objUrl)
  while (blobLRU.size > BLOB_LIMIT) {
    const oldestKey = blobLRU.keys().next().value as string | undefined
    if (!oldestKey) break
    const o = blobLRU.get(oldestKey)
    if (o) URL.revokeObjectURL(o)
    blobLRU.delete(oldestKey)
  }
}

/* ===================== 工具 & 解析 ===================== */
function placeholderDataUri(label = '无图'): string {
  const svg = `
    <svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>
      <rect width='100%' height='100%' fill='#f3f4f6'/>
      <text x='50%' y='50%' dominant-baseline='middle' text-anchor='middle'
            font-family='-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial' font-size='22'
            fill='#9ca3af'>${label}</text>
    </svg>`.replace(/\n+/g,'').trim()
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}
function normalizeName(raw?: string) {
  const s = (raw || '').trim()
  return s.replace(/\s+/g,'').replace(/[·•・．。、《》〈〉“”"'`’‘()（）:：;；,，.!！?？]/g,'')
}

function buildCandidates(m: Monster, override?: (m: Monster) => string | null) {
  const list: string[] = []
  const ov = override?.(m)
  if (ov) list.push(ov)

  const ex = (m as any)?.explain_json?.image_url
  if (typeof ex === 'string' && ex) list.push(String(ex))

  const BASE_A = import.meta.env.VITE_MONSTER_IMG_BASE || '/media/monsters'
  const BASE_B = '/images/monsters'
  const names = Array.from(new Set([m.name, (m as any).name_final].filter(Boolean).map(normalizeName))) as string[]
  const exts = ['gif', 'jpg', 'png', 'jpeg', 'webp']

  for (const base of [BASE_A, BASE_B]) {
    for (const n of names) {
      for (const ext of exts) {
        list.push(`${base}/${encodeURIComponent(n)}.${ext}`)
        list.push(`${base}/${encodeURIComponent('G'+n)}.${ext}`)
      }
    }
  }
  return { list, cacheKey: `${(m as any)?.id ?? ''}::${names.join('|')}` }
}

async function resolveImageOnce(
  cacheKey: string,
  candidates: string[],
  preferBlob = true
): Promise<string | null> {
  if (resolvedUrlCache.has(cacheKey)) return resolvedUrlCache.get(cacheKey) ?? null
  const existing = resolvingCache.get(cacheKey)
  if (existing) return existing

  const p = (async () => {
    for (const url of candidates) {
      try {
        if (preferBlob) {
          const cachedBlob = blobGet(url)
          if (cachedBlob) { resolvedUrlCache.set(cacheKey, cachedBlob); return cachedBlob }
          const resp = await fetch(url, { cache: 'force-cache' })
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          const blob = await resp.blob()
          if (blob.size === 0) throw new Error('empty blob')
          const objUrl = URL.createObjectURL(blob)
          blobSet(url, objUrl)
          resolvedUrlCache.set(cacheKey, objUrl)
          return objUrl
        } else {
          await new Promise<void>((resolve, reject) => {
            const img = new Image()
            img.onload = () => resolve()
            img.onerror = () => reject(new Error('load fail'))
            img.src = url
          })
          resolvedUrlCache.set(cacheKey, url)
          return url
        }
      } catch {}
    }
    resolvedUrlCache.set(cacheKey, null)
    return null
  })()

  resolvingCache.set(cacheKey, p)
  const ret = await p.finally(() => resolvingCache.delete(cacheKey))
  return ret
}

function useImageResolved(m: Monster, override?: (m: Monster) => string | null) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    const { list, cacheKey } = buildCandidates(m, override)
    if (resolvedUrlCache.has(cacheKey)) {
      const v = resolvedUrlCache.get(cacheKey) ?? null
      setSrc(v)
      if (v) return
    }
    resolveImageOnce(cacheKey, list, true).then((v) => { if (!cancelled) setSrc(v) })
    return () => { cancelled = true }
  }, [m, override])
  return src
}

async function prewarmImages(monsters: Monster[], override?: (m: Monster) => string | null, count = 80) {
  const tasks: Promise<any>[] = []
  for (let i = 0; i < Math.min(count, monsters.length); i++) {
    const m = monsters[i]
    const { list, cacheKey } = buildCandidates(m, override)
    if (resolvedUrlCache.has(cacheKey)) continue
    tasks.push(resolveImageOnce(cacheKey, list, true))
  }
  await Promise.allSettled(tasks)
}

/* ===================== 卡片组件 ===================== */
function MonsterCard(props: {
  m: Monster
  selected: boolean
  onToggleSelect: (id: number) => void
  onOpenDetail: (m: Monster) => void
  showRawSummary: boolean
  getImageUrl?: (m: Monster) => string | null
  ribbon: Ribbon
  mediaHeightCss: string
}) {
  const { m, selected, onToggleSelect, onOpenDetail, showRawSummary, getImageUrl, ribbon, mediaHeightCss } = props
  const imgUrl = useImageResolved(m, getImageUrl) || placeholderDataUri()

  const wrapRef = useRef<HTMLDivElement>(null)
  const [wrapSize, setWrapSize] = useState({ w: 0, h: 0 })
  const [nat, setNat] = useState({ w: 0, h: 0 })
  const isGif = /\.gif($|\?)/i.test(imgUrl)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect
      setWrapSize({ w: r.width, h: r.height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const intScale = useMemo(() => {
    if (!isGif || !nat.w || !nat.h || !wrapSize.w || !wrapSize.h) return 1
    const byH = Math.floor(wrapSize.h / nat.h)
    const byW = Math.floor(wrapSize.w / nat.w)
    return Math.max(1, Math.min(byH, byW, 3))
  }, [isGif, nat, wrapSize])

  const rawSum =
    (m.hp || 0) + (m.speed || 0) + (m.attack || 0) +
    (m.defense || 0) + (m.magic || 0) + (m.resist || 0)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpenDetail(m)}
      onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onOpenDetail(m) }}}
      className={[
        'relative rounded-lg border border-gray-200 bg-white shadow-sm',
        'hover:shadow-md transition-shadow focus:outline-none focus:ring-2 focus:ring-blue-300',
        selected ? 'ring-2 ring-purple-300' : '',
        'p-2.5'
      ].join(' ')}
    >
      {ribbon && (
        <div className="absolute left-2 top-2 z-10">
          <span className={['inline-flex items-center rounded-full px-1.5 py-[2px] text-[10px] font-medium text-white shadow-sm',
            ribbon.colorClass || 'bg-orange-500'].join(' ')}>
            {ribbon.text}
          </span>
        </div>
      )}

      <div
        className="absolute right-2 top-2 z-10"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <label className="inline-flex items-center gap-1 bg-white/90 backdrop-blur rounded-md px-1.5 py-[2px] shadow-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={selected}
            onChange={() => onToggleSelect(m.id)}
            aria-label={`选择 ${m.name}`}
          />
        </label>
      </div>

      {/* 图片内框 */}
      <div
        ref={wrapRef}
        className="w-full overflow-hidden rounded-md border border-gray-200/70 bg-white flex items-center justify-center"
        style={{ height: mediaHeightCss }}
      >
        <img
          src={imgUrl}
          alt={m.name}
          loading="eager"
          draggable={false}
          onLoad={(e) => {
            const el = e.currentTarget
            setNat({ w: el.naturalWidth, h: el.naturalHeight })
          }}
          style={
            isGif && nat.w && nat.h && intScale > 1
              ? { width: nat.w * intScale, height: nat.h * intScale, imageRendering: 'pixelated' as any }
              : { imageRendering: isGif ? ('pixelated' as any) : undefined }
          }
          className="max-h-full w-auto object-contain"
        />
      </div>

      {/* 文本区 */}
      <div className="px-1.5 pb-2 pt-2">
        <div className="truncate text-center text-[13px] font-semibold">{m.name}</div>
        <div className="mt-0.5 flex items-center justify-center gap-1 text-[11px] text-gray-500">
          <span className="whitespace-nowrap">{m.element || '—'}</span>
          {m.possess && <span className="badge badge-info">已拥有</span>}
          {/* 已移除“可获取”徽标 */}
        </div>
        <div className="mt-1 text-center">
          {props.showRawSummary ? (
            <span className="inline-block rounded-full bg-gray-100 px-1.5 py-[2px] text-[10px]">
              六维总和：<b>{rawSum}</b>
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/* ===================== 网格容器：自适应列 + 预热 ===================== */
export default function MonsterCardGrid({
  items,
  selectedIds,
  onToggleSelect,
  onOpenDetail,
  showRawSummary = true,
  getImageUrl,
  computeRibbon,
  minCardWidthPx = 160,
  mediaHeightCss = 'clamp(110px, 18vw, 180px)',
  className,
}: Props) {
  useEffect(() => {
    BLOB_LIMIT = Number(import.meta.env.VITE_IMG_BLOB_LIMIT || BLOB_LIMIT_DEFAULT)
    const cb = () => prewarmImages(items, getImageUrl, 80)
    if ('requestIdleCallback' in window) {
      const id = (window as any).requestIdleCallback(cb)
      return () => (window as any).cancelIdleCallback?.(id)
    } else {
      const t = setTimeout(cb, 0)
      return () => clearTimeout(t)
    }
  }, [items, getImageUrl])

  const gridStyle: React.CSSProperties = useMemo(() => ({
    gridTemplateColumns: `repeat(auto-fit, minmax(${minCardWidthPx}px, 1fr))`,
    gap: 'clamp(6px, 1.6vw, 12px)',
  }), [minCardWidthPx])

  return (
    <div className={['grid', className].filter(Boolean).join(' ')} style={gridStyle}>
      {items.map((m) => (
        <MonsterCard
          key={m.id}
          m={m}
          selected={selectedIds.has(m.id)}
          onToggleSelect={onToggleSelect}
          onOpenDetail={onOpenDetail}
          showRawSummary={showRawSummary}
          getImageUrl={getImageUrl}
          ribbon={computeRibbon ? computeRibbon(m) : null}
          mediaHeightCss={mediaHeightCss}
        />
      ))}
    </div>
  )
}