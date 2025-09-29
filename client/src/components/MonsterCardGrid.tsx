// client/src/components/MonsterCardGrid.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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

// 缓存元数据：记录创建时间用于过期检查
const cacheMetadata = new Map<string, { timestamp: number; accessed: number }>()
const CACHE_EXPIRY_MS = 30 * 60 * 1000 // 30分钟过期
const MAX_ACCESS_COUNT = 50 // 最大访问次数后重新验证

function blobGet(url: string) {
  const v = blobLRU.get(url)
  if (v) { 
    blobLRU.delete(url)
    blobLRU.set(url, v)
    
    // 更新访问元数据
    const meta = cacheMetadata.get(url)
    if (meta) {
      meta.accessed++
      cacheMetadata.set(url, meta)
    }
  }
  return v || null
}

function blobSet(url: string, objUrl: string) {
  if (blobLRU.has(url)) {
    const oldUrl = blobLRU.get(url)
    if (oldUrl) URL.revokeObjectURL(oldUrl)
    blobLRU.delete(url)
  }
  
  blobLRU.set(url, objUrl)
  cacheMetadata.set(url, { timestamp: Date.now(), accessed: 0 })
  
  while (blobLRU.size > BLOB_LIMIT) {
    const oldestKey = blobLRU.keys().next().value as string | undefined
    if (!oldestKey) break
    const o = blobLRU.get(oldestKey)
    if (o) URL.revokeObjectURL(o)
    blobLRU.delete(oldestKey)
    cacheMetadata.delete(oldestKey)
  }
}

// 缓存健康检查和清理
function cleanupExpiredCache() {
  const now = Date.now()
  const expiredKeys: string[] = []
  
  for (const [key, meta] of cacheMetadata.entries()) {
    if (now - meta.timestamp > CACHE_EXPIRY_MS || meta.accessed > MAX_ACCESS_COUNT) {
      expiredKeys.push(key)
    }
  }
  
  expiredKeys.forEach(key => {
    // 清理 blob cache
    const blobUrl = blobLRU.get(key)
    if (blobUrl) {
      URL.revokeObjectURL(blobUrl)
      blobLRU.delete(key)
    }
    
    // 清理 resolved cache
    resolvedUrlCache.delete(key)
    cacheMetadata.delete(key)
  })
  
  if (expiredKeys.length > 0) {
    console.log(`Cleaned up ${expiredKeys.length} expired cache entries`)
  }
}

// 定期清理缓存
setInterval(cleanupExpiredCache, 5 * 60 * 1000) // 每5分钟清理一次

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
  const exts = ['png']

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
  // 检查过期缓存
  const meta = cacheMetadata.get(cacheKey)
  if (meta && (Date.now() - meta.timestamp > CACHE_EXPIRY_MS || meta.accessed > MAX_ACCESS_COUNT)) {
    resolvedUrlCache.delete(cacheKey)
    cacheMetadata.delete(cacheKey)
  }
  
  if (resolvedUrlCache.has(cacheKey)) return resolvedUrlCache.get(cacheKey) ?? null
  const existing = resolvingCache.get(cacheKey)
  if (existing) return existing

  const p = (async () => {
    const TIMEOUT_MS = 8000 // 8秒超时
    
    for (const url of candidates) {
      try {
        if (preferBlob) {
          const cachedBlob = blobGet(url)
          if (cachedBlob) { 
            resolvedUrlCache.set(cacheKey, cachedBlob)
            return cachedBlob 
          }
          
          // 带超时的 fetch
          const controller = new AbortController()
          const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS)
          
          try {
            const resp = await fetch(url, { 
              cache: 'force-cache',
              signal: controller.signal
            })
            clearTimeout(timeoutId)
            
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
            const blob = await resp.blob()
            if (blob.size === 0) throw new Error('empty blob')
            
            // 验证是否为有效图片
            const objUrl = URL.createObjectURL(blob)
            await new Promise<void>((resolve, reject) => {
              const img = new Image()
              img.onload = () => resolve()
              img.onerror = () => {
                URL.revokeObjectURL(objUrl)
                reject(new Error('invalid image blob'))
              }
              img.src = objUrl
            })
            
            blobSet(url, objUrl)
            resolvedUrlCache.set(cacheKey, objUrl)
            return objUrl
          } catch (error) {
            clearTimeout(timeoutId)
            throw error
          }
        } else {
          // 带超时的图片加载
          await new Promise<void>((resolve, reject) => {
            const img = new Image()
            const timeoutId = setTimeout(() => {
              img.onload = img.onerror = null
              reject(new Error('timeout'))
            }, TIMEOUT_MS)
            
            img.onload = () => {
              clearTimeout(timeoutId)
              resolve()
            }
            img.onerror = () => {
              clearTimeout(timeoutId)
              reject(new Error('load fail'))
            }
            img.src = url
          })
          resolvedUrlCache.set(cacheKey, url)
          return url
        }
      } catch (error) {
        // 记录详细错误信息用于调试
        console.debug(`Failed to load image from ${url}:`, error)
      }
    }
    resolvedUrlCache.set(cacheKey, null)
    return null
  })()

  resolvingCache.set(cacheKey, p)
  const ret = await p.finally(() => resolvingCache.delete(cacheKey))
  return ret
}

// 图片加载状态类型
type ImageLoadState = 'loading' | 'loaded' | 'error' | 'retrying'

function useImageResolved(m: Monster, override?: (m: Monster) => string | null) {
  const [src, setSrc] = useState<string | null>(null)
  const [loadState, setLoadState] = useState<ImageLoadState>('loading')
  const [retryCount, setRetryCount] = useState(0)
  const maxRetries = 3
  const retryDelays = [1000, 2000, 4000] // 递增延迟

  const loadImage = useCallback(async (isRetry = false) => {
    if (isRetry) {
      setLoadState('retrying')
    } else {
      setLoadState('loading')
      setRetryCount(0)
    }
    
    let cancelled = false
    const { list, cacheKey } = buildCandidates(m, override)
    
    // 检查缓存
    if (resolvedUrlCache.has(cacheKey)) {
      const v = resolvedUrlCache.get(cacheKey) ?? null
      if (v) {
        setSrc(v)
        setLoadState('loaded')
        return
      }
    }

    try {
      const result = await resolveImageOnce(cacheKey, list, true)
      if (!cancelled) {
        setSrc(result)
        setLoadState(result ? 'loaded' : 'error')
      }
    } catch (error) {
      if (!cancelled) {
        setSrc(null)
        setLoadState('error')
      }
    }

    return () => { cancelled = true }
  }, [m, override])

  // 重试机制
  const retryLoad = useCallback(() => {
    if (retryCount < maxRetries) {
      const delay = retryDelays[retryCount] || 4000
      setTimeout(() => {
        setRetryCount(prev => prev + 1)
        loadImage(true)
      }, delay)
    }
  }, [retryCount, maxRetries, loadImage])

  // 手动重试
  const manualRetry = useCallback(() => {
    // 清除相关缓存
    const { cacheKey } = buildCandidates(m, override)
    resolvedUrlCache.delete(cacheKey)
    resolvingCache.delete(cacheKey)
    
    setRetryCount(0)
    loadImage(false)
  }, [m, override, loadImage])

  useEffect(() => {
    loadImage()
  }, [loadImage])

  // 自动重试
  useEffect(() => {
    if (loadState === 'error' && retryCount < maxRetries) {
      retryLoad()
    }
  }, [loadState, retryCount, maxRetries, retryLoad])

  return { src, loadState, retryCount, manualRetry }
}

async function prewarmImages(monsters: Monster[], override?: (m: Monster) => string | null, count = 80) {
  // 分批预热，避免一次性发起太多请求
  const BATCH_SIZE = 10
  const BATCH_DELAY = 100 // 批次间延迟100ms
  
  const batches: Monster[][] = []
  const total = Math.min(count, monsters.length)
  
  for (let i = 0; i < total; i += BATCH_SIZE) {
    batches.push(monsters.slice(i, i + BATCH_SIZE))
  }
  
  let successCount = 0
  let errorCount = 0
  
  for (const batch of batches) {
    const tasks = batch.map(async (m) => {
      const { list, cacheKey } = buildCandidates(m, override)
      
      // 跳过已缓存的
      if (resolvedUrlCache.has(cacheKey)) {
        successCount++
        return
      }
      
      try {
        const result = await resolveImageOnce(cacheKey, list, true)
        if (result) {
          successCount++
        } else {
          errorCount++
        }
      } catch (error) {
        errorCount++
        console.debug(`Prewarm failed for ${m.name}:`, error)
      }
    })
    
    await Promise.allSettled(tasks)
    
    // 批次间延迟，减少服务器压力
    if (batches.indexOf(batch) < batches.length - 1) {
      await new Promise(resolve => setTimeout(resolve, BATCH_DELAY))
    }
  }
  
  console.log(`Image prewarming completed: ${successCount} success, ${errorCount} failed`)
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
  const { src, loadState, retryCount, manualRetry } = useImageResolved(m, getImageUrl)
  const imgUrl = src || placeholderDataUri(loadState === 'loading' ? '加载中' : loadState === 'retrying' ? '重试中' : '无图')

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
        className="w-full overflow-hidden rounded-md border border-gray-200/70 bg-white flex items-center justify-center relative"
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
        
        {/* 加载状态指示器 */}
        {(loadState === 'loading' || loadState === 'retrying') && (
          <div className="absolute inset-0 bg-gray-50/80 flex items-center justify-center">
            <div className="flex flex-col items-center gap-1">
              <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
              <span className="text-xs text-gray-600">
                {loadState === 'retrying' ? `重试中 ${retryCount}/3` : '加载中'}
              </span>
            </div>
          </div>
        )}
        
        {/* 错误状态与重试按钮 */}
        {loadState === 'error' && !src && (
          <div className="absolute inset-0 bg-gray-50/90 flex items-center justify-center">
            <div className="flex flex-col items-center gap-2">
              <span className="text-xs text-gray-500">图片加载失败</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  manualRetry()
                }}
                className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
                title="重新加载图片"
              >
                重试
              </button>
            </div>
          </div>
        )}
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
        {/* 战斗倾向显示 */}
        {m.attack_tendency && m.defense_tendency && (
          <div className="mt-1 text-center">
            <div className="flex justify-center gap-1">
              <span className="inline-block rounded-full bg-gradient-to-r from-red-100 to-orange-100 px-1.5 py-[2px] text-[9px] font-medium">
                {m.attack_tendency}
              </span>
              <span className="inline-block rounded-full bg-gradient-to-r from-blue-100 to-purple-100 px-1.5 py-[2px] text-[9px] font-medium">
                {m.defense_tendency}
              </span>
            </div>
          </div>
        )}
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

/* ===================== 导出的工具函数 ===================== */
// 清理所有图片缓存（用于故障恢复）
export function clearAllImageCache() {
  // 清理 blob URLs
  for (const objUrl of blobLRU.values()) {
    URL.revokeObjectURL(objUrl)
  }
  blobLRU.clear()
  
  // 清理缓存
  resolvedUrlCache.clear()
  resolvingCache.clear()
  cacheMetadata.clear()
  
  console.log('All image cache cleared')
}

// 获取缓存统计信息
export function getImageCacheStats() {
  return {
    blobCount: blobLRU.size,
    resolvedCount: resolvedUrlCache.size,
    resolvingCount: resolvingCache.size,
    memoryUsage: `${Math.round(blobLRU.size * 0.1)}MB (estimated)`,
    cacheHitRate: cacheMetadata.size > 0 ? 
      `${Math.round(Array.from(cacheMetadata.values()).reduce((sum, meta) => sum + meta.accessed, 0) / cacheMetadata.size * 100)}%` : 
      'N/A'
  }
}