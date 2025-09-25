// client/src/pages/MonstersPage.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import SideDrawer from '../components/SideDrawer'
import { useSettings } from '../context/SettingsContext'
import MonsterCardGrid from '../components/MonsterCardGrid'
import SkeletonCardGrid from '../components/SkeletonCardGrid'
import TagSelector from '../components/TagSelector'
import SkillRecommendationHelper from '../components/SkillRecommendationHelper'
import Modal from '../components/Modal'
import MonsterStatsRadar from '../components/MonsterStatsRadar'

// 适配新后端：技能带 element/kind/power/description
type SkillDTO = {
  id?: number
  name: string
  element?: string | null
  kind?: string | null
  power?: number | null
  pp?: number | null
  description?: string
  selected?: boolean
}

type StatsDTO = { total: number; with_skills?: number; tags_total?: number }
type WarehouseStatsDTO = {
  total?: number
  owned_total?: number
  not_owned_total?: number
  in_warehouse?: number // 兼容字段
}


// 排序键：原生六维与六维总和
type SortKey =
  | 'updated_at'
  | 'hp' | 'speed' | 'attack' | 'defense' | 'magic' | 'resist' | 'raw_sum'


const BTN_FX = 'transition active:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300'
const LIMIT_TAGS_PER_CELL = 3

// 文本小工具
const isMeaningfulDesc = (t?: string) => {
  if (!t) return false
  const s = t.trim()
  const trivial = new Set(['', '0', '1', '-', '—', '无', '暂无', 'null', 'none', 'N/A', 'n/a'])
  if (trivial.has(s) || trivial.has(s.toLowerCase())) return false
  return s.length >= 6 || /[，。；、,.]/.test(s) ||
    /(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)/.test(s)
}
const isValidSkillName = (name?: string) => !!(name && name.trim() && /[\u4e00-\u9fffA-Za-z]/.test(name))

// —— 新标签体系前端适配：严格只认 buf_* / deb_* / util_* —— //
type TagBuckets = { buf: string[]; deb: string[]; util: string[] }
const bucketizeTags = (tags: string[] | undefined): TagBuckets => {
  const b: TagBuckets = { buf: [], deb: [], util: [] }
  for (const t of (tags || [])) {
    if (t.startsWith('buf_')) b.buf.push(t)
    else if (t.startsWith('deb_')) b.deb.push(t)
    else if (t.startsWith('util_')) b.util.push(t)
  }
  return b
}
const tagEmoji = (code: string) =>
  code.startsWith('buf_') ? '🟢' : code.startsWith('deb_') ? '🔴' : code.startsWith('util_') ? '🟣' : ''

// 放在 MonstersPage.tsx 顶部工具区
const toURLParams = (obj: Record<string, any>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(obj)) {
    if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) continue
    if (k === 'tags_all' && Array.isArray(v)) {
      v.forEach((t) => p.append('tags_all', t))   // ← 重复 key，无中括号
    } else if (Array.isArray(v)) {
      v.forEach((x) => p.append(k, String(x)))
    } else {
      p.append(k, String(v))
    }
  }
  return p
}

// —— 完整元素映射（code -> 中文），以及选项数组 —— //
const ELEMENTS: Record<string, string> = {
  huoxi: '火系', jinxi: '金系', muxi: '木系', shuixi: '水系', tuxi: '土系', yixi: '翼系',
  guaixi: '怪系', moxi: '魔系', yaoxi: '妖系', fengxi: '风系', duxi: '毒系', leixi: '雷系',
  huanxi: '幻系', bing: '冰系', lingxi: '灵系', jixie: '机械系', huofengxi: '火风系',
  mulingxi: '木灵系', tuhuanxi: '土幻系', shuiyaoxi: '水妖系', yinxi: '音系', shengxi: '圣系',
  teshu: '特殊',
}
const elementOptionsFull = Array.from(new Set(Object.values(ELEMENTS)))

// —— 元素简称（技能属性）到中文元素映射 —— //
const SHORT_ELEMENT_TO_LABEL: Record<string, string> = {
  火: '火系', 水: '水系', 风: '风系', 雷: '雷系', 冰: '冰系', 木: '木系',
  土: '土系', 金: '金系', 圣: '圣系', 毒: '毒系', 幻: '幻系', 灵: '灵系',
  妖: '妖系', 魔: '魔系', 音: '音系', 机械: '机械系', 特殊: '特殊' // 技能特殊属性
}

// —— 进度弹框状态（新增 cancelable + closing） —— //
type OverlayState = {
  show: boolean
  title?: string
  sub?: string
  total?: number
  done?: number
  ok?: number
  fail?: number
  cancelable?: boolean
  closing?: boolean
}


const RAW_COLUMNS = [
  { key: 'hp', label: '体' },
  { key: 'attack', label: '攻' },
  { key: 'magic', label: '法' },
  { key: 'defense', label: '防' },
  { key: 'resist', label: '抗' },
  { key: 'speed', label: '速' },
] as const

export default function MonstersPage() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  

  // 搜索 + 筛选
  const [q, setQ] = useState('')
  const [elements, setElements] = useState<string[]>([])  // 多元素筛选（中文数组）
  const [acqType, setAcqType] = useState('')           // 获取途径

  // === 新增：收藏分组筛选 ===
  const [collectionId, setCollectionId] = useState<number | ''>('')

  // === 新增：对面属性（vs）用于标注倍率（仅文本，不着色） ===
  const [vsElement, setVsElement] = useState('')       // 对面属性（中文，空则不启用）

  // 三组标签（多选支持）
  const [tagBufList, setTagBufList] = useState<string[]>([])
  const [tagDebList, setTagDebList] = useState<string[]>([])
  const [tagUtilList, setTagUtilList] = useState<string[]>([])
  const [tagBufMode, setTagBufMode] = useState<'all' | 'any'>('all')
  const [tagDebMode, setTagDebMode] = useState<'all' | 'any'>('all')
  const [tagUtilMode, setTagUtilMode] = useState<'all' | 'any'>('all')
  const selectedTags = useMemo(() => [...tagBufList, ...tagDebList, ...tagUtilList], [tagBufList, tagDebList, tagUtilList])

  // ✅ 原始六维默认展示 + 默认按六维总和排序
  const [sort, setSort] = useState<SortKey>('raw_sum')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const sortForApi = sort
  const [warehouseOnly, setWarehouseOnly] = useState(false) // 仅看仓库（已拥有）
  const [notOwnedOnly, setNotOwnedOnly] = useState(false)   // 仅看未获取

  // 分页
  const [page, setPage] = useState(1)
  const { pageSize, crawlLimit } = useSettings()
  // 勾选/批量
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // 详情 & 编辑
  const [selected, setSelected] = useState<Monster | any | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editElement, setEditElement] = useState('')
  const [editRole, setEditRole] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editType, setEditType] = useState<string>('')
  const [editMethod, setEditMethod] = useState<string>('')

  // —— 六维 —— //
  const [hp, setHp] = useState<number>(100)
  const [speed, setSpeed] = useState<number>(100)
  const [attack, setAttack] = useState<number>(100)
  const [defense, setDefense] = useState<number>(100)
  const [magic, setMagic] = useState<number>(100)
  const [resist, setResist] = useState<number>(100)

  // 技能编辑：卡片列表
  const [editSkills, setEditSkills] = useState<SkillDTO[]>([])

  // 技能显示控制：默认只显示推荐技能
  const [showAllSkills, setShowAllSkills] = useState(false)


  const [saving, setSaving] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)

  // —— 新增模式 & 识别链接框 —— //
  const [isCreating, setIsCreating] = useState<boolean>(false)
  const [rawText, setRawText] = useState<string>('')         // 这里改成贴“链接”
  const [recognizing, setRecognizing] = useState<boolean>(false)

  // 全屏模糊等待弹框 + 真实进度（类型化 + 可取消）
  const [overlay, setOverlay] = useState<OverlayState>({ show: false })

  // —— "加入收藏"弹框 —— //
  const [collectionDialogOpen, setCollectionDialogOpen] = useState(false)

  // —— 简洁爬取创建弹框 —— //
  const [crawlDialogOpen, setCrawlDialogOpen] = useState(false)
  const [crawlUrl, setCrawlUrl] = useState('')
  const [crawling, setCrawling] = useState(false)
  const [collectionForm, setCollectionForm] = useState<{
    mode: 'existing' | 'new',
    selectedId: string,
    name: string,
    color: string
  }>({ mode: 'existing', selectedId: '', name: '', color: '' })

  // —— 视图切换（列表/卡片），默认 card，并做本地持久化 —— //
  const [view, setView] = useState<'table' | 'card'>(() => {
    const v = typeof window !== 'undefined' ? window.localStorage.getItem('monsters_view') : null
    return (v === 'table' || v === 'card') ? (v as any) : 'card'
  })
  useEffect(() => {
    try { window.localStorage.setItem('monsters_view', view) } catch {}
  }, [view])

  // —— 弹框“最短显示 + 淡出关闭” —— //
  const OVERLAY_MIN_VISIBLE_MS = 1000
  const overlayShownAtRef = useRef<number>(0)
  const closingGuardRef = useRef(false)

  useEffect(() => {
    if (!overlay.show) return
    overlayShownAtRef.current = Date.now()
    // 只有“不是在关闭流程里”的 closing: true 才视为入场淡入
    if (overlay.closing && !closingGuardRef.current) {
      const raf = requestAnimationFrame(() => {
        setOverlay(prev => ({ ...prev, closing: false }))
      })
      return () => cancelAnimationFrame(raf)
    }
  }, [overlay.show, overlay.closing])

  const smoothCloseOverlay = () => {
    const since = Date.now() - (overlayShownAtRef.current || Date.now())
    const wait = Math.max(0, OVERLAY_MIN_VISIBLE_MS - since)
    setTimeout(() => {
      closingGuardRef.current = true
      setOverlay(prev => ({ ...prev, cancelable: false, closing: true }))
      setTimeout(() => {
        setOverlay({ show: false })
        closingGuardRef.current = false
      }, 500) // 与 JSX 的 duration-500 对齐
    }, wait)
  }
  // —— 一键爬取 —— //

  const startCrawl = async () => {
    if (!window.confirm(`将触发后端“全站爬取图鉴”。${crawlLimit ? `最多抓取 ${crawlLimit} 条。` : '将尽可能多地抓取。'}是否继续？`)) return
    setCrawling(true)
    try {
      const payload: any = {}
      if (crawlLimit && /^\d+$/.test(crawlLimit)) payload.limit = parseInt(crawlLimit, 10)
      const res = await api.post('/api/v1/crawl/crawl_all', payload)
      const d = res?.data || {}
      const fetched = d.fetched ?? d.seen ?? 0
      alert(`完成：遍历 ${fetched}，新增 ${d.inserted||0}，更新 ${d.updated||0}，技能变更 ${d.skills_changed||0}`)
      await Promise.all([list.refetch(), stats.refetch(), wstats.refetch()])
      if (selected) {
        const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
        setSelected(fresh)
      }
    } catch (e:any) {
      alert('触发失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
    } finally {
      setCrawling(false)
    }
  }

  // === 新增：全局事件监听（TopBar 发出 kb:crawl 时，这里调用原有 startCrawl） ===
  const startCrawlRef = useRef<() => void>(() => {})
  useEffect(() => { startCrawlRef.current = startCrawl }, [startCrawl])
  useEffect(() => {
    const handler = () => startCrawlRef.current?.()
    window.addEventListener('kb:crawl', handler)
    return () => window.removeEventListener('kb:crawl', handler)
  }, [])

  // ====== 标签 i18n（code -> 中文），无接口时兜底空对象 ======
  const tagI18n = useQuery({
    queryKey: ['tag_i18n'],
    queryFn: async () => {
      try {
        const r1 = await api.get('/tags/i18n')
        return (r1.data?.i18n || r1.data || {}) as Record<string, string>
      } catch {
        try {
          const r2 = await api.get('/tags/catalog')
          return (r2.data?.i18n || {}) as Record<string, string>
        } catch {
          return {} as Record<string, string>
        }
      }
    },
    staleTime: 5 * 60 * 1000,
  })

  const tagLabel = (code: string) =>
    (tagI18n.data && typeof (tagI18n.data as any)[code] === 'string')
      ? (tagI18n.data as any)[code]
      : code

  // 所有标签计数（来自后端；不可用时用当前页兜底）
  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      try {
        const d = (await api.get('/tags', { params: { with_counts: true } })).data
        const arr: TagCount[] = Array.isArray(d) ? d : (d?.items || [])
        return (arr || []).filter(t =>
          t?.name?.startsWith('buf_') || t?.name?.startsWith('deb_') || t?.name?.startsWith('util_')
        )
      } catch {
        return [] as TagCount[]
      }
    }
  })

  // =============== 收藏夹列表（用于筛选和加入弹框） ===============
  const collections = useQuery({
    queryKey: ['collections'],
    queryFn: async () => {
      const d = (await api.get('/collections')).data
      // 兼容 { items: [...] } 或直接数组
      return Array.isArray(d?.items) ? d.items : (Array.isArray(d) ? d : [])
    },
    staleTime: 2 * 60 * 1000
  })

  // =============== 对面属性倍率：分别按“我打他(attack)”和“他打我(defense)”取数，并合并成对显示 ===============
  const typeEffectsAtk = useQuery({
    queryKey: ['type_effects', 'attack', vsElement],
    enabled: !!vsElement,
    queryFn: async () => {
      const d = (await api.get('/types/effects', { params: { vs: vsElement, perspective: 'attack' } })).data
      return d
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const typeEffectsDef = useQuery({
    queryKey: ['type_effects', 'defense', vsElement],
    enabled: !!vsElement,
    queryFn: async () => {
      const d = (await api.get('/types/effects', { params: { vs: vsElement, perspective: 'defense' } })).data
      return d
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  // 小工具：倍率文本格式（2.0 / 1.5 / 0.75 / 0.875）
  const formatMultiplier = (m: any) => {
    const x = Number(m)
    if (!Number.isFinite(x)) return ''
    if (Math.abs(x - Math.round(x)) < 1e-9) return x.toFixed(1)      // 2.0
    if (Math.abs(x * 4 - Math.round(x * 4)) < 1e-9) return x.toFixed(2) // .25/.75
    if (Math.abs(x * 8 - Math.round(x * 8)) < 1e-9) return x.toFixed(3) // .125/.875
    return String(x)
  }

  // 合并成：元素 → { atk, def, label: "×atk/×def" }
  type EffectPair = { atk?: number; def?: number; label?: string }
  const effectsPairByType = useMemo(() => {
    const m: Record<string, EffectPair> = {}

    const add = (items: any[] | undefined | null, key: 'atk' | 'def') => {
      if (!items) return
      for (const it of items) {
        const k = it?.type ?? it?.name
        if (!k) continue
        if (!m[k]) m[k] = {}
        const mult = Number(it?.multiplier ?? it?.value)
        if (Number.isFinite(mult)) m[k][key] = mult
      }
    }

    add(typeEffectsAtk.data?.items, 'atk')   // 我打他
    add(typeEffectsDef.data?.items, 'def')   // 他打我

    for (const [k, v] of Object.entries(m)) {
      const a = v.atk != null ? `×${formatMultiplier(v.atk)}` : ''
      const d = v.def != null ? `×${formatMultiplier(v.def)}` : ''
      v.label = a && d ? `${a}/${d}` : (a || d || '')
    }
    return m
  }, [typeEffectsAtk.data, typeEffectsDef.data])

  // ======== 新增：把 (atk, def) 分类 + 计算强弱，用于元素下拉排序 ========
  const classifyPair = (pair?: EffectPair) => {
    const aRaw = Number(pair?.atk)
    const dRaw = Number(pair?.def)
    const a = Number.isFinite(aRaw) ? aRaw : 1
    const d = Number.isFinite(dRaw) ? dRaw : 1
    const eps = 1e-9
    const atkRel = a > 1 + eps ? 1 : a < 1 - eps ? -1 : 0   // 攻：>1 优，<1 劣
    const defRel = d < 1 - eps ? 1 : d > 1 + eps ? -1 : 0   // 受：<1 优，>1 劣

    // 组别（数字越小越靠前）
    // 0：攻优+受优；1：仅受优；2：仅攻优；3：全中立；4：仅攻劣；5：仅受劣；6：全劣
    let group = 3
    if (atkRel === 1 && defRel === 1) group = 0
    else if (defRel === 1 && atkRel === 0) group = 1
    else if (atkRel === 1 && defRel === 0) group = 2
    else if (atkRel === 0 && defRel === 0) group = 3
    else if (atkRel === -1 && defRel === 0) group = 4
    else if (atkRel === 0 && defRel === -1) group = 5
    else if (atkRel === -1 && defRel === -1) group = 6

    // 优势强度（越大越好）：攻(>1) + 受(<1)
    const advMag = Math.max(0, a - 1) + Math.max(0, 1 - d)
    // 劣势强度（越小越好）：攻(<1) + 受(>1)
    const disadvMag = Math.max(0, 1 - a) + Math.max(0, d - 1)

    return { group, advMag, disadvMag }
  }

  // ======== 新增：百分比格式化（用于下拉文本显示“攻±X%/受±Y%”） ========
  const formatPct = (v: number) => {
    if (!Number.isFinite(v)) return '0%'
    const abs = Math.abs(v)
    let num: number
    if (Math.abs(v - Math.round(v)) < 1e-9) num = Math.round(v)
    else if (Math.abs(v * 10 - Math.round(v * 10)) < 1e-9) num = Math.round(v * 10) / 10
    else num = Math.round(v * 100) / 100
    const sign = v > 0 ? '+' : v < 0 ? '-' : ''
    return `${sign}${Math.abs(num)}%`
  }

  const percentLabelForPair = (pair?: EffectPair) => {
    if (!pair) return ''
    const a = Number.isFinite(Number(pair.atk)) ? Number(pair.atk) : 1
    const d = Number.isFinite(Number(pair.def)) ? Number(pair.def) : 1
    const atkPct = (a - 1) * 100      // 攻：倍率相对 1 的增减
    const defPct = (1 - d) * 100      // 受：倍率越小越好，所以用 (1-d)
    return `攻${formatPct(atkPct)}/受${formatPct(defPct)}`
  }
  // ======== 百分比格式化（结束） ========

  // 计算：用于“元素筛选（顶部第 1 个下拉）”的选项（文本显示百分比，value 仍是纯中文元素名）
  const filterElementOptionsLabeled = useMemo(() => {
    if (vsElement) {
      const opts = elementOptionsFull.map((value) => {
        const pair = effectsPairByType[value]
        const { group, advMag, disadvMag } = classifyPair(pair)
        // —— 在下拉处改用百分比 —— //
        const pctText = percentLabelForPair(pair)
        const text = pctText ? `${value}（${pctText}）` : value
        return { value, text, group, advMag, disadvMag }
      })

      // 排序规则
      opts.sort((a, b) => {
        if (a.group !== b.group) return a.group - b.group
        if (a.group <= 2) return b.advMag - a.advMag
        if (a.group === 3) return String(a.value).localeCompare(String(b.value), 'zh')
        return a.disadvMag - b.disadvMag
      })

      return opts.map(({ value, text }) => ({ value, text }))
    }
    return elementOptionsFull.map(el => ({ value: el, text: el }))
  }, [vsElement, effectsPairByType])

  // —— 列表数据 —— //
  const list = useQuery({
    queryKey: ['monsters', {
      q, elements, tagBufList, tagDebList, tagUtilList, tagBufMode, tagDebMode, tagUtilMode, acqType, sort: sortForApi, order,
      page, pageSize, warehouseOnly, notOwnedOnly, collectionId,   // ← 增加 collectionId
    }],
    queryFn: async () => {
      const baseParams: any = {
        q: q || undefined,
        elements: elements.length > 0 ? elements : undefined,  // 多元素数组
        type: acqType || undefined,
        acq_type: acqType || undefined,
        sort: sortForApi, order,
        page,
        page_size: pageSize,
        collection_id: collectionId || undefined,  // ← 收藏筛选
      }
      // 使用新的多选标签系统
      if (tagBufList.length > 0) {
        if (tagBufMode === 'all') baseParams.buf_tags_all = tagBufList
        else baseParams.buf_tags_any = tagBufList
      }
      if (tagDebList.length > 0) {
        if (tagDebMode === 'all') baseParams.deb_tags_all = tagDebList
        else baseParams.deb_tags_any = tagDebList
      }
      if (tagUtilList.length > 0) {
        if (tagUtilMode === 'all') baseParams.util_tags_all = tagUtilList
        else baseParams.util_tags_any = tagUtilList
      }

      // ✅ 只要“仓库”或“未获取”任一开启，就走 /warehouse
      if (warehouseOnly || notOwnedOnly) {
        if (warehouseOnly) baseParams.possess = true
        if (notOwnedOnly)  baseParams.possess = false
        return (await api.get('/warehouse', { params: toURLParams(baseParams) })).data as MonsterListResp
      }

      // 默认：全库
      return (await api.get('/monsters', { params: toURLParams(baseParams) })).data as MonsterListResp
    },
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  // —— 当 /tags 不可用时，用当前页 items 的 tags 做临时计数 —— //
  const localTagCounts: TagCount[] = useMemo(() => {
    if (tags.data && tags.data.length > 0) return tags.data
    const map = new Map<string, number>()
    for (const m of (list.data?.items || [])) {
      for (const t of ((m as any).tags || [])) {
        if (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_')) {
          map.set(t, (map.get(t) || 0) + 1)
        }
      }
    }
    return Array.from(map.entries()).map(([name, count]) => ({ name, count }))
  }, [tags.data, list.data])

  // 将计数拆成三组并排序（count desc + i18n asc）
  const { bufCounts, debCounts, utilCounts } = useMemo(() => {
    const source = (tags.data && tags.data.length > 0) ? tags.data : localTagCounts
    const sortFn = (a: TagCount, b: TagCount) => {
      if ((b.count || 0) !== (a.count || 0)) return (b.count || 0) - (a.count || 0)
      const la = tagLabel(a.name), lb = tagLabel(b.name)
      return String(la).localeCompare(String(lb), 'zh')
    }
    const buf = source.filter(t => t.name.startsWith('buf_')).sort(sortFn)
    const deb = source.filter(t => t.name.startsWith('deb_')).sort(sortFn)
    const util = source.filter(t => t.name.startsWith('util_')).sort(sortFn)
    return { bufCounts: buf, debCounts: deb, utilCounts: util }
  }, [tags.data, localTagCounts, tagI18n.data])

  // 总数（统计栏保留原样）
  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get('/stats')).data as StatsDTO
  })
  // 仓库数量（严格以 /warehouse 的 total 为准）
  const wstats = useQuery({
    queryKey: ['warehouse_stats_v2'],
    queryFn: async () => {
      return (await api.get('/warehouse/stats')).data as WarehouseStatsDTO
    }
  })

  const skills = useQuery({
    queryKey: ['skills', (selected as any)?.id],
    enabled: !!(selected as any)?.id,
    queryFn: async () => (await api.get(`/monsters/${(selected as any)!.id}/skills`)).data as SkillDTO[]
  })

  // —— 展示用六维 —— //
  const showStats = selected ? {
    hp: (selected as any).hp || 0,
    speed: (selected as any).speed || 0,
    attack: (selected as any).attack || 0,
    defense: (selected as any).defense || 0,
    magic: (selected as any).magic || 0,
    resist: (selected as any).resist || 0,
    sum: ((selected as any).hp||0)+((selected as any).speed||0)+((selected as any).attack||0)+((selected as any).defense||0)+((selected as any).magic||0)+((selected as any).resist||0),
  } : { hp: 0, speed: 0, attack: 0, defense: 0, magic: 0, resist: 0, sum: 0 }

  const sum = useMemo(() => hp + speed + attack + defense + magic + resist,
    [hp, speed, attack, defense, magic, resist])

  // —— 批量选择 —— //
  const toggleOne = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const toggleAllVisible = () => {
    const ids = (filteredItems as any[])?.map(i => i.id) || []
    const allSelected = ids.length > 0 && ids.every(id => selectedIds.has(id))
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allSelected) ids.forEach(id => next.delete(id))
      else ids.forEach(id => next.add(id))
      return next
    })
  }
  const clearSelection = () => setSelectedIds(new Set())

  // —— 批量删除 —— //
  const bulkDelete = async () => {
    if (!selectedIds.size) return
    if (!window.confirm(`确认删除选中的 ${selectedIds.size} 条记录？此操作不可撤销。`)) return
    const ids = Array.from(selectedIds)
    try {
      await api.delete('/monsters/bulk_delete', { data: { ids }, headers: { 'Content-Type': 'application/json' } })
    } catch {
      await api.post('/monsters/bulk_delete', { ids })
    }
    clearSelection()
    list.refetch()
    stats.refetch()
    wstats.refetch()
  }
  const deleteOne = async (id: number) => {
    if (!window.confirm('确认删除该宠物？此操作不可撤销。')) return
    await api.delete(`/monsters/${id}`)
    if ((selected as any)?.id === id) setSelected(null)
    list.refetch(); stats.refetch(); wstats.refetch()
  }


  // —— 打开详情 —— //
  const openDetail = (m: Monster | any) => {
    setSelected(m)
    setIsEditing(false)
  }

  // —— 进入编辑（技能改为卡片列表）—— //
  const enterEdit = () => {
    if (!selected) return
    const s: any = selected
    setEditName(s.name || s.name_final || '')
    setEditElement(s.element || '')
    setEditRole(s.role || '')
    // 仓库状态已移至AddMonsterDrawer组件内部处理
    setEditType(s.type || '')
    setEditMethod(s.method || '')

    const onlyNew = (s.tags || []).filter((t: string) => t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))
    setEditTags(onlyNew.join(' '))

    setHp(Math.round(s.hp ?? 100))
    setSpeed(Math.round(s.speed ?? 100))
    setAttack(Math.round(s.attack ?? 100))
    setDefense(Math.round(s.defense ?? 100))
    setMagic(Math.round(s.magic ?? 100))
    setResist(Math.round(s.resist ?? 100))

    const rows: SkillDTO[] = (skills.data || [])
      .filter(x => isValidSkillName(x.name))
      .map(x => ({
        id: x.id,
        name: x.name,
        element: x.element ?? '',
        kind: x.kind ?? '',
        power: x.power ?? null,
        pp: x.pp ?? null,
        description: x.description ?? '',
        selected: x.selected ?? false
      }))
    setEditSkills(rows.length ? rows : [{ name: '', element: '', kind: '', power: null, pp: null, description: '', selected: false }])

    setIsEditing(true)
  }
  const cancelEdit = () => {
    if (isCreating) {
      setIsCreating(false)
      setSelected(null)
      setIsEditing(false)
      setRawText('')
      return
    }
    setIsEditing(false)
  }

  // —— 技能保存（裸数组优先 + 清洗去重） —— //
  const saveSkills = async (monsterId: number, body: SkillDTO[]) => {
    // 1) 规范化 + 去空名 + 去重（按 name）
    const seen = new Set<string>()
    const skills = body
      .map(s => {
        const power =
          (typeof s.power === 'number' && Number.isFinite(s.power)) ? s.power : undefined
        return {
          name: (s.name || '').trim(),
          element: (s.element || '').trim() || undefined,
          kind: (s.kind || '').trim() || undefined,
          power,
          description: (s.description || '').trim(),
          selected: s.selected,
        }
      })
      .filter(s => isValidSkillName(s.name))
      .filter(s => {
        if (seen.has(s.name)) return false
        seen.add(s.name)
        return true
      })
      .map(s => {
        const o: any = { name: s.name }
        if (s.element) o.element = s.element
        if (s.kind) o.kind = s.kind
        if (Number.isFinite(s.power as number)) o.power = Number(s.power)
        if (isMeaningfulDesc(s.description)) o.description = s.description
        if (typeof s.selected === 'boolean') o.selected = s.selected
        return o
      })

    // 2) 新接口：PUT + 裸数组
    try {
      return await api.put(`/monsters/${monsterId}/skills`, skills, {
        headers: { 'Content-Type': 'application/json' }
      })
    } catch (e1: any) {
      // 3) 老接口兜底
      try {
        return await api.post('/skills/set', { monster_id: monsterId, skills })
      } catch (e2: any) {
        const msg = e1?.response?.data?.detail || e2?.response?.data?.detail ||
                    e1?.message || e2?.message || '保存技能失败'
        throw new Error(msg)
      }
    }
  }

  // —— 保存整体（编辑已有） —— //
  const saveEdit = async () => {
    if (!selected) return
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      await api.put(`/monsters/${(selected as any).id}`, {
        name: editName.trim(),
        element: editElement || null,
        role: editRole || null,
        type: editType || null,
        method: editMethod || null,
        hp, speed, attack, defense, magic, resist,
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))),
      })

      await saveSkills((selected as any).id, editSkills)

      const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
      setSelected(fresh)
      skills.refetch()
      list.refetch()
      stats.refetch()
      wstats.refetch()
      setIsEditing(false)
    } catch (e: any) {
      alert(e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // —— 保存整体（创建新建） —— //
  const saveCreate = async () => {
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      const body: any = {
        name: editName.trim(),
        element: editElement || null,
        possess: editRole === '拥有' || false, // 将role字段转换为possess布尔值
        type: editType || null,
        method: editMethod || null,
        hp, speed, attack, defense, magic, resist,
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))),
        skills: editSkills.filter(s => s.name.trim()).map(s => ({
          name: s.name.trim(),
          element: s.element || null,
          kind: s.kind || null,
          power: typeof s.power === 'number' ? s.power : null,
          pp: typeof s.pp === 'number' ? s.pp : null,
          description: s.description || '',
          selected: s.selected || false
        }))
      }

      let res
      try {
        // 直接使用正确的API路径
        res = await api.post('/monsters', body)
      } catch (e1: any) {
        // 如果失败，显示详细错误信息
        const errorMsg = e1?.response?.data?.detail || e1?.message || '创建失败'
        alert(`创建失败：${errorMsg}`)
        return
      }

      const newId = res?.data?.id ?? res?.data?.monster?.id ?? res?.data?.data?.id
      if (!newId) {
        alert('创建成功但未返回有效ID')
        return
      }

      await list.refetch()
      await stats.refetch()
      await wstats.refetch()

      if (newId) {
        const fresh = (await api.get(`/monsters/${newId}`)).data as Monster
        setSelected(fresh)
      }

      setIsCreating(false)
      setIsEditing(false)
      setRawText('')
      alert('创建完成')
    } catch (e: any) {
      alert(e?.response?.data?.detail || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  // —— 主页一键自动匹配（保留，走原接口） —— //
  const autoMatchBatch = async () => {
    const items = (list.data?.items as any[]) || []
    if (!items.length) return alert('当前没有可处理的记录')
    const target = selectedIds.size ? items.filter(i => selectedIds.has(i.id)) : items
    if (!target.length) return alert('请勾选一些记录，或直接对当前页可见项执行。')
    if (!window.confirm(`将对 ${target.length} 条记录执行“自动匹配”（后端推断定位+建议标签并保存）。是否继续？`)) return

    setAutoMatching(true)
    try {
      try {
        await api.post('/monsters/auto_match', { ids: target.map((x: any) => x.id) })
      } catch (e: any) {
        const ids = target.map((x: any) => x.id)
        for (const id of ids) {
          try { await api.post(`/tags/monsters/${id}/retag`) } catch {}
        }
      }
      await list.refetch()
      if (selected) {
        const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
        setSelected(fresh)
      }
      alert('自动匹配完成')
    } catch (e: any) {
      alert(e?.response?.data?.detail || '自动匹配失败')
    } finally {
      setAutoMatching(false)
    }
  }

  // —— 工具：根据当前筛选收集“全部要处理的 IDs”（未勾选时用它） —— //
  const collectAllTargetIds = async (): Promise<number[]> => {
    const useWarehouse = warehouseOnly || notOwnedOnly
    const endpoint = useWarehouse ? '/warehouse' : '/monsters'
    const pageSizeFetch = 200
    let pageNo = 1
    let total = 0
    const ids: number[] = []

    while (true) {
      const params: any = {
        q: q || undefined,
        elements: elements.length > 0 ? elements : undefined,  // 多元素数组
        type: acqType || undefined,
        acq_type: acqType || undefined,
        sort: sortForApi, order,
        page: pageNo,
        page_size: pageSizeFetch,
        collection_id: collectionId || undefined, // ← 收藏筛选透传
      }
      // 使用新的多选标签系统
      if (tagBufList.length > 0) {
        if (tagBufMode === 'all') params.buf_tags_all = tagBufList
        else params.buf_tags_any = tagBufList
      }
      if (tagDebList.length > 0) {
        if (tagDebMode === 'all') params.deb_tags_all = tagDebList
        else params.deb_tags_any = tagDebList
      }
      if (tagUtilList.length > 0) {
        if (tagUtilMode === 'all') params.util_tags_all = tagUtilList
        else params.util_tags_any = tagUtilList
      }

      if (useWarehouse) {
        if (warehouseOnly) params.possess = true
        if (notOwnedOnly)  params.possess = false
      }

      const resp = await api.get(endpoint, { params: toURLParams(params) })
      const data = resp.data as MonsterListResp
      const arr = (data.items as any[]) || []
      ids.push(...arr.map(x => x.id))
      total = data.total || ids.length
      if (arr.length === 0 || ids.length >= total) break
      pageNo += 1
    }
    return Array.from(new Set(ids))
  }

  // —— "取消 AI 打标签"标记 —— //
  const cancelAITagRef = useRef(false)
  const cancelResolveRef = useRef<(() => void) | null>(null)
  const currentJobIdRef = useRef<string | null>(null)

  // —— 一键：打完标签后再统一分析（静默版：无 alert，完成后清除勾选） —— //
  const aiTagThenDeriveBatch = async () => {
    const targetIds: number[] = selectedIds.size
      ? Array.from(selectedIds)
      : await collectAllTargetIds()

    if (!targetIds.length) return

    // 阶段 1：AI 打标签
    cancelAITagRef.current = false
    setOverlay({
      show: true,
      title: 'AI 打标签进行中…',
      sub: '正在分析文本与技能',
      total: targetIds.length,
      done: 0,
      ok: 0,
      fail: 0,
      cancelable: true,
      closing: true
    })

    let cancelled = false
    let batchCompleted = false

    try {
      // 使用批量AI接口
      try {
        // 启动批量任务
        setOverlay(prev => ({ ...prev, sub: '正在启动批量处理任务' }))
        const startResp = await api.post('/tags/ai_batch/start', { ids: targetIds })
        const jobId = startResp.data.job_id
        currentJobIdRef.current = jobId  // 保存jobId供取消按钮使用
        
        // 轮询进度
        let pollInterval: number | null = null
        await new Promise<void>((resolve, reject) => {
          cancelResolveRef.current = resolve  // 保存resolve函数供取消按钮使用
          const pollProgress = async () => {
            try {
              const progressResp = await api.get(`/tags/ai_batch/${jobId}`)
              const progress = progressResp.data
              
              // 更新进度
              setOverlay(prev => ({
                ...prev,
                title: progress.running ? 'AI 打标签进行中…' : '任务完成',
                sub: progress.running 
                  ? `已处理 ${progress.processed || 0}/${progress.total} (${Math.round(progress.percent || 0)}%)` 
                  : '正在更新数据',
                done: progress.done || 0,
                ok: progress.done || 0,
                fail: progress.failed || 0,
                cancelable: progress.running
              }))
              
              if (!progress.running) {
                if (pollInterval) clearTimeout(pollInterval)
                // 根据是否取消显示不同的结果
                const title = progress.canceled ? '任务已取消' : '批量标签匹配完成'
                const sub = progress.canceled 
                  ? `已取消，已处理: ${progress.done || 0}/${progress.total || 0}` 
                  : `成功: ${progress.done || 0}, 失败: ${progress.failed || 0}, 总计: ${progress.total || 0}`
                
                setOverlay(prev => ({
                  ...prev,
                  title,
                  sub,
                  cancelable: false
                }))
                // 立即完成，不延迟
                resolve()
                // 立即关闭弹窗
                setTimeout(() => smoothCloseOverlay(), 100)
                return
              }
              
              pollInterval = setTimeout(pollProgress, 300)
            } catch (error) {
              if (pollInterval) clearTimeout(pollInterval)
              reject(error)
            }
          }
          pollProgress()
        })
        
        // 批量处理成功完成
        batchCompleted = true
        cancelResolveRef.current = null  // 清理resolve引用
        currentJobIdRef.current = null  // 清理jobId引用
        
      } catch (batchError) {
        console.error('批量处理失败，回退到单个处理:', batchError)
        // 回退到单个处理模式
        setOverlay(prev => ({ ...prev, title: '使用单个处理模式', sub: '批量模式失败，回退到单个处理', done: 0, ok: 0, fail: 0 }))
        
        for (const id of targetIds) {
          if (cancelAITagRef.current) { cancelled = true; break }
          try {
            try {
              await api.post(`/tags/monsters/${id}/retag_ai`)
            } catch {
              await api.post(`/tags/monsters/${id}/retag`)
            }
            setOverlay(prev => ({
              ...prev,
              done: (prev.done || 0) + 1,
              ok: (prev.ok || 0) + 1
            }))
          } catch {
            setOverlay(prev => ({
              ...prev,
              done: (prev.done || 0) + 1,
              fail: (prev.fail || 0) + 1
            }))
          }
        }
      }

      // 阶段 2：统一分析 (批量处理成功时跳过)
      if (!cancelled && !batchCompleted) {
        setOverlay({
          show: true,
          title: '分析中…',
          sub: '正在分析妖怪数据',
          cancelable: false,
          closing: true
        })
      }
    } finally {
      try {
        await Promise.all([
          list.refetch(),
          wstats.refetch(),
          stats.refetch()
        ])
        if (selected) {
          try {
            const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
            setSelected(fresh)
          } catch {}
        }
      } catch {}

      setSelectedIds(new Set())
      // 如果批量处理成功完成，不要立即关闭弹窗，让用户看到结果
      if (!batchCompleted) {
        smoothCloseOverlay()
      }
      cancelAITagRef.current = false
      cancelResolveRef.current = null  // 清理所有引用
      currentJobIdRef.current = null
    }
  }

  // —— 一键全部分析（成功静默） —— //

  // === 保留原始元素数组供“编辑表单/技能编辑”等处使用（纯文本，不带倍率） ===
  const elementOptions = elementOptionsFull
  const acquireTypeOptions = [
    '无双宠物', '神宠', '珍宠', '罗盘宠物', 
    'BOSS宠物', '可捕捉宠物', 'VIP宠物', '商城宠物', 
    '任务宠物', '超进化宠物', '活动宠物', '其他宠物'
  ]

  // —— 批量加入/移出仓库 —— //
  const bulkSetWarehouse = async (flag: boolean) => {
    if (!selectedIds.size) return
    const ids = Array.from(selectedIds)
    await api.post('/warehouse/bulk_set', { ids, possess: flag })
    clearSelection()
    list.refetch()
    wstats.refetch()
  }

  // —— 批量加入收藏 —— //
  const openAddToCollection = () => {
    if (!selectedIds.size) return
    setCollectionDialogOpen(true)
  }

  const submitAddToCollection = async () => {
    if (!selectedIds.size) { setCollectionDialogOpen(false); return }
    try {
      let targetId: number | null = null

      if (collectionForm.mode === 'existing') {
        if (!collectionForm.selectedId) {
          alert('请选择一个已有分组，或切换到“新建分组”。')
          return
        }
        targetId = Number(collectionForm.selectedId)
      } else {
        const name = (collectionForm.name || '').trim()
        if (!name) { alert('请填写新分组名称'); return }
        const created = (await api.post('/collections', { name, color: collectionForm.color || undefined })).data
        // 兼容 {id} 或 { data: {id} } 或 { item: {id} }
        targetId = created?.id ?? created?.data?.id ?? created?.item?.id
        if (!targetId) throw new Error('创建分组成功但未返回 ID')
      }

      const ids = Array.from(selectedIds)
      await api.post(`/collections/${targetId}/add`, { ids }, { headers: { 'Content-Type': 'application/json' } })

      alert(`已加入收藏（${ids.length} 项）`)
      setCollectionDialogOpen(false)
      setCollectionForm({ mode: 'existing', selectedId: '', name: '', color: '' })
      setSelectedIds(new Set())
      // 刷新收藏计数 & 列表
      queryClient.invalidateQueries({ queryKey: ['collections'] })
      list.refetch()
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || '加入收藏失败')
    }
  }

  // —— 批量从当前收藏组移除（新增） —— //
  const removeSelectedFromCollection = async () => {
    if (!collectionId) return
    const ids = Array.from(selectedIds)
    if (!ids.length) return
    if (!window.confirm(`从当前收藏组移除 ${ids.length} 项？`)) return
    try {
      await api.post(`/collections/${collectionId}/remove`, { ids }, { headers: { 'Content-Type': 'application/json' } })
      setSelectedIds(new Set())
      await Promise.all([
        list.refetch(),
        queryClient.invalidateQueries({ queryKey: ['collections'] }),
      ])
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || '移出失败')
    }
  }

  // —— 删除当前收藏组（新增） —— //
  const deleteCurrentCollection = async () => {
    if (!collectionId) return
    if (!window.confirm('删除该收藏组？组内关联会被清空（妖怪不会删除）。')) return
    try {
      await api.delete(`/collections/${collectionId}`)
      setCollectionId('')
      setSelectedIds(new Set())
      await Promise.all([
        list.refetch(),
        queryClient.invalidateQueries({ queryKey: ['collections'] }),
      ])
    } catch (e: any) {
      alert(e?.response?.data?.detail || e?.message || '删除失败')
    }
  }

  // —— 重命名当前收藏组（新增） —— //
  const openRenameCollection = async () => {
    if (!collectionId) return
    const cur = collections.data?.find((c:any) => String(c.id) === String(collectionId))
    const name = window.prompt('输入新的分组名称：', cur?.name || '')
    if (name == null) return
    const trimmed = name.trim()
    if (!trimmed) { alert('名称不能为空'); return }
    try {
      await api.patch(`/collections/${collectionId}`, { name: trimmed })
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
    } catch (e:any) {
      alert(e?.response?.data?.detail || e?.message || '重命名失败')
    }
  }

  // 小工具：更新/增删技能
  const updateSkill = (idx: number, patch: Partial<SkillDTO>) => {
    setEditSkills(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s))
  }
  const removeSkill = (idx: number) => setEditSkills(prev => prev.filter((_, i) => i !== idx))
  const addSkill = () => setEditSkills(prev => [...prev, { name: '', element: '', kind: '', power: null, pp: null, description: '', selected: false }])

  // 编辑态时，保证至少有一条空卡可写
  useEffect(() => {
    if (isEditing && editSkills.length === 0) {
      setEditSkills([{ name: '', element: '', kind: '', power: null, pp: null, description: '', selected: false }])
    }
  }, [isEditing, editSkills.length])

  // 计算进度百分比
  const progressPct = overlay.total ? Math.floor(((overlay.done || 0) / overlay.total) * 100) : null

  // —— 列表数据（现在由后端完全处理标签过滤） —— //
  const filteredItems = useMemo(() => {
    return (list.data?.items as any[]) || []
  }, [list.data])

  // —— 新建：初始化清空并打开编辑抽屉 —— //
  const startCreate = () => {
    setIsCreating(true)
    setSelected({ id: 0 })
    setRawText('')
    setEditName('')
    setEditElement('')
    setEditRole('')
    setEditTags('')
    // 仓库状态已移至AddMonsterDrawer组件内部处理
    setEditType('')
    setEditMethod('')
    setHp(100); setSpeed(100); setAttack(100); setDefense(100); setMagic(100); setResist(100)
    setEditSkills([{ name: '', element: '', kind: '', power: null, pp: null, description: '', selected: false }])
    setIsEditing(true)
  }

  // ========== 简洁爬取创建功能 ==========
  const handleCrawlAndCreate = async () => {
    const url = crawlUrl.trim()
    if (!url) {
      alert('请输入妖怪详情页链接')
      return
    }

    setCrawling(true)
    try {
      // 直接调用爬取并入库的接口
      const result = (await api.post('/api/v1/crawl/fetch_and_save', { 
        url, 
        process_image: true,
        enable_upscale: true,
        overwrite: false
      })).data

      if (!result.success) {
        // 处理失败情况
        if (result.detail && result.detail.includes('已存在')) {
          const confirmOverwrite = window.confirm(`${result.detail}\n\n是否覆盖更新现有记录？`)
          if (confirmOverwrite) {
            // 重新调用，允许覆盖
            const retryResult = (await api.post('/api/v1/crawl/fetch_and_save', { 
              url, 
              process_image: true,
              enable_upscale: true,
              overwrite: true
            })).data
            
            if (!retryResult.success) {
              alert(`更新失败：${retryResult.detail}`)
              return
            }
            
            // 使用更新后的结果
            handleSuccess(retryResult)
            return
          } else {
            // 用户选择不覆盖，直接返回
            return
          }
        } else {
          alert(`爬取失败：${result.detail}`)
          return
        }
      }

      // 成功处理
      handleSuccess(result)

    } catch (e: any) {
      const errorMsg = e?.response?.data?.detail || e?.message || '操作失败'
      alert(`爬取失败：${errorMsg}`)
    } finally {
      setCrawling(false)
    }
  }

  const handleSuccess = async (result: any) => {
    // 刷新列表
    await list.refetch()
    await stats.refetch()
    await wstats.refetch()

    const data = result.data
    const imgStatus = data?.img_processed ? 
      (data.img_url ? '✅ 图片已下载并处理' : '⚠️ 图片处理失败') : 
      'ℹ️ 未处理图片'
    
    const actionText = result.is_insert ? '创建' : '更新'
    alert(`妖怪 "${data?.name || '未知'}" ${actionText}成功！\n\n${imgStatus}${data?.img_url ? `\n图片路径: ${data.img_url}` : ''}`)
    
    // 关闭弹框并清理
    setCrawlDialogOpen(false)
    setCrawlUrl('')
  }

  // ========== 识别链接功能（旧版，保留兼容） ==========
  const extractUrls = (text: string): string[] => {
    const re = /https?:\/\/[^\s)（）]+/gi
    const raw = text.match(re) || []
    const clean = raw
      .map(u => u.replace(/[)，。；;,]+$/, ''))
      .map(s => s.trim())
      .filter(Boolean)
    return Array.from(new Set(clean))
  }

  const recognizeAndPrefillFromLinks = async () => {
    const urls = extractUrls(rawText)
    if (!urls.length) {
      alert('请在文本框中粘贴至少一个怪物详情页链接（支持 4399 图鉴详情页）')
      return
    }
    const url = urls[0]
    setRecognizing(true)
    try {
      let data: any
      try {
        // 推荐：POST JSON（包含图片处理选项）
        data = (await api.post('/api/v1/crawl/fetch_one', { 
          url, 
          process_image: true,  // 启用图片处理
          enable_upscale: true  // 启用图片超分
        })).data
      } catch {
        // 兜底：GET query（包含图片处理选项）
        data = (await api.get('/api/v1/crawl/fetch_one', { 
          params: { 
            url, 
            process_image: true, 
            enable_upscale: true 
          } 
        })).data
      }
      if (!data || typeof data !== 'object') {
        alert('未识别到有效数据'); return
      }

      // 基础信息
      if (data.name) setEditName(data.name)
      if (data.element) setEditElement(data.element)
      // 仓库状态已移至AddMonsterDrawer组件内部处理
      if (data.type) setEditType(data.type)
      if (data.method) setEditMethod(data.method)

      // 六维（优先覆盖为 >0 的数值）
      const n = (x: any) => (typeof x === 'number' && Number.isFinite(x) ? x : null)
      const hv = (k: string) => Math.max(0, n(data[k]) ?? 0)
      if (n(data.hp) != null) setHp(hv('hp'))
      if (n(data.speed) != null) setSpeed(hv('speed'))
      if (n(data.attack) != null) setAttack(hv('attack'))
      if (n(data.defense) != null) setDefense(hv('defense'))
      if (n(data.magic) != null) setMagic(hv('magic'))
      if (n(data.resist) != null) setResist(hv('resist'))

      // 技能（selected_skills）
      const rows: SkillDTO[] = Array.isArray(data.selected_skills) ? data.selected_skills
        .filter((s: any) => isValidSkillName(s?.name))
        .map((s: any) => ({
          name: s.name || '',
          element: s.element || '',
          kind: s.kind || '',
          power: (typeof s.power === 'number' && Number.isFinite(s.power)) ? s.power : null,
          pp: (typeof s.pp === 'number' && Number.isFinite(s.pp)) ? s.pp : null,
          description: s.description || '',
          selected: s.selected ?? false
        }))
        : []
      setEditSkills(rows.length ? rows : [{ name: '', element: '', kind: '', power: null, pp: null, description: '', selected: false }])

      // 显示识别成功信息，包含图片处理状态
      const imgStatus = data.img_processed ? 
        (data.img_url ? '✅ 图片已下载并处理' : '⚠️ 图片处理失败') : 
        'ℹ️ 未处理图片'
      alert(`已从链接识别并填充，可继续手动调整。\n\n${imgStatus}${data.img_url ? `\n图片路径: ${data.img_url}` : ''}`)
    } catch (e: any) {
      const errorMsg = e?.response?.data?.detail || e?.message || '识别失败'
      if (errorMsg.includes('fetch failed')) {
        alert('识别失败：无法解析该链接。\n\n请确认：\n1. 链接是最新的4399图鉴详情页\n2. URL格式类似：https://news.4399.com/kabuxiyou/yaoguaidaquan/[系别]/[日期]-[编号].html\n3. 页面可以正常访问')
      } else {
        alert(`识别失败：${errorMsg}\n\n请确认链接是否可访问，或尝试使用最新的图鉴详情页URL`)
      }
    } finally {
      setRecognizing(false)
    }
  }
  // ========== 识别链接功能（结束） ==========

  // 计算“本页可见是否全选”
  const allVisibleSelected = useMemo(() => {
    const ids = filteredItems.map(i => i.id)
    return ids.length > 0 && ids.every(id => selectedIds.has(id))
  }, [filteredItems, selectedIds])

  // ✅ 依据模式选择统计列、排序选项与骨架列数
  const STAT_COLS = RAW_COLUMNS  // Always show raw stats now
  const totalCols = 4 /* 选择+ID+名称+元素 */ + STAT_COLS.length + 3 /* 三组标签 */

  const sortOptions = [
    { value: 'updated_at', label: '更新时间' },
    { value: 'raw_sum', label: '六维总和' },
    { value: 'hp', label: '体力' },
    { value: 'attack', label: '攻击' },
    { value: 'magic', label: '法术' },
    { value: 'defense', label: '防御' },
    { value: 'resist', label: '抗性' },
    { value: 'speed', label: '速度' },
  ] as {value: SortKey, label: string}[]

  // —— 获取途径角标：基于新的12类分类，优先级：无双 > 神宠 > 珍宠 > 罗盘 > VIP > 超进化 > BOSS > 活动 > 任务 > 可捕捉 —— //
  const computeRibbon = (m: Monster) => {
    const type = m.type || ''
    
    // 直接匹配新的分类名称
    if (type === '无双宠物') return { text: '无双', colorClass: 'bg-purple-600' }
    if (type === '神宠') return { text: '神宠', colorClass: 'bg-yellow-500' }
    if (type === '珍宠') return { text: '珍宠', colorClass: 'bg-pink-500' }
    if (type === '罗盘宠物') return { text: '罗盘', colorClass: 'bg-indigo-500' }
    if (type === 'VIP宠物') return { text: 'VIP', colorClass: 'bg-green-500' }
    if (type === '超进化宠物') return { text: '超进化', colorClass: 'bg-orange-500' }
    if (type === 'BOSS宠物') return { text: 'BOSS', colorClass: 'bg-red-500' }
    if (type === '活动宠物') return { text: '活动', colorClass: 'bg-blue-500' }
    if (type === '任务宠物') return { text: '任务', colorClass: 'bg-cyan-500' }
    if (type === '可捕捉宠物') return { text: '可捕捉', colorClass: 'bg-lime-500' }
    if (type === '商城宠物') return { text: '商城', colorClass: 'bg-amber-500' }
    
    // 如果是其他宠物，不显示角标
    return null
  }


  return (
    <div className="container my-6 space-y-4">
      {/* 顶部工具栏 */}
      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {/* 收藏组管理 */}
            {collectionId && (
              <>
                <button
                  className={`btn ${BTN_FX}`}
                  onClick={openRenameCollection}
                  title="重命名当前收藏组"
                >
                  重命名收藏组
                </button>
                <button
                  className={`btn ${BTN_FX}`}
                  onClick={deleteCurrentCollection}
                  title="删除当前收藏组"
                >
                  删除收藏组
                </button>
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            
            <button className={`btn ${BTN_FX}`} onClick={aiTagThenDeriveBatch}>
              一键匹配
            </button>

            {/* 仓库开关（已拥有） */}
            <button
              className={`btn ${warehouseOnly ? 'btn-primary' : ''} ${BTN_FX}`}
              onClick={() => { setWarehouseOnly(v => { const next = !v; if (next) setNotOwnedOnly(false); return next }); setPage(1) }}
              title="只显示仓库已有的宠物 / 再次点击还原"
            >
              仓库妖怪
            </button>

            {/* 未获取妖怪（未拥有） */}
            <button
              className={`btn ${notOwnedOnly ? 'btn-primary' : ''} ${BTN_FX}`}
              onClick={() => { setNotOwnedOnly(v => { const next = !v; if (next) setWarehouseOnly(false); return next }); setPage(1) }}
              title="只显示未获取的宠物 / 再次点击还原"
            >
              未获取妖怪
            </button>

            {/* 新增：视图切换（列表/卡片） */}
            <button
              className={`btn ${BTN_FX}`}
              title="切换表格/卡片视图"
              onClick={() => setView(v => (v === 'card' ? 'table' : 'card'))}
            >
              {view === 'card' ? '表格视图' : '卡片视图'}
            </button>

            {/* 新增：新增妖怪（简洁爬取模式） */}
            <button className={`btn ${BTN_FX}`} onClick={() => setCrawlDialogOpen(true)}>新增妖怪</button>
          </div>
        </div>

        {/* 1 行：搜索 */}
        <div className="mb-3">
          <div className="grid grid-cols-1 gap-3 min-w-0">
            <input
              className="input w-full min-w-0"
              placeholder="搜索名称 / 技能关键词…"
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              aria-label="搜索"
            />
          </div>
        </div>

        {/* 2 行：基础筛选器 */}
        <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-3">
          {/* 对面属性——仅用于给"元素下拉"标注百分比并排序 */}
          <select className="select" value={vsElement} onChange={e => { setVsElement(e.target.value); }}>
            <option value="">对面属性</option>
            {elementOptionsFull.map(el => <option key={el} value={el}>{el}</option>)}
          </select>


          <select className="select" value={acqType} onChange={e => { setAcqType(e.target.value); setPage(1) }}>
            <option value="">获取途径</option>
            {acquireTypeOptions.map(t => <option key={t} value={t}>{t}</option>)}
          </select>

          {/* 收藏分组筛选 */}
          <select
            className="select"
            value={collectionId === '' ? '' : String(collectionId)}
            onChange={(e) => { const v = e.target.value; setCollectionId(v ? Number(v) as number : ''); setPage(1) }}
            title="按收藏分组筛选"
          >
            <option value="">全部收藏</option>
            {collections.data?.map((c: any) => (
              <option key={c.id} value={String(c.id)}>
                {c.name}{typeof c.items_count === 'number' ? `（${c.items_count}）` : ''}
              </option>
            ))}
          </select>

          {/* 排序选项 */}
          <select
            className="select"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
          >
            {sortOptions.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>

          <select className="select" value={order} onChange={e => setOrder(e.target.value as any)}>
            <option value="desc">降序</option>
            <option value="asc">升序</option>
          </select>
        </div>


        {/* 筛选区域：元素 + 技能标签 */}
        <div className="mb-3">
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            {/* 元素筛选 */}
            <div className="space-y-2">
              
              {/* 多元素筛选下拉 */}
              <div className="relative">
                <select 
                  className="select w-full" 
                  value=""
                  onChange={e => { 
                    if (e.target.value) {
                      const newElement = e.target.value
                      if (!elements.includes(newElement)) {
                        setElements([...elements, newElement])
                        setPage(1)
                      }
                      e.target.value = '' // 重置选择
                    }
                  }}
                >
                  <option value="">+ 选择元素</option>
                  {filterElementOptionsLabeled
                    .filter(opt => !elements.includes(opt.value))
                    .map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.text}</option>
                    ))
                  }
                </select>
              </div>
              
              {/* 已选元素标签 */}
              {elements.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {elements.map(element => (
                    <span key={element} className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-orange-100 text-orange-800 rounded border border-orange-200">
                      {element}
                      {vsElement && effectsPairByType[element]?.label && (
                        <span className="text-orange-600">({effectsPairByType[element].label})</span>
                      )}
                      <button
                        className="text-orange-500 hover:text-orange-800 ml-1"
                        onClick={() => {
                          setElements(elements.filter(e => e !== element))
                          setPage(1)
                        }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 增强标签 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <select className="select flex-1" value="" onChange={e => {
                  if (e.target.value && !tagBufList.includes(e.target.value)) {
                    setTagBufList([...tagBufList, e.target.value])
                    setPage(1)
                  }
                  e.target.value = ''
                }}>
                  <option value="">🟢 增强 (+)</option>
                  {bufCounts.filter(t => !tagBufList.includes(t.name)).map(t =>
                    <option key={t.name} value={t.name}>
                      {`${tagLabel(t.name)}（${t.count}）`}
                    </option>
                  )}
                </select>
                <select className="select w-20" value={tagBufMode} onChange={e => { setTagBufMode(e.target.value as 'all' | 'any'); setPage(1) }}>
                  <option value="all">AND</option>
                  <option value="any">OR</option>
                </select>
              </div>
              {tagBufList.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tagBufList.map(tag => (
                    <span key={tag} className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-800 rounded text-sm">
                      🟢{tagLabel(tag)}
                      <button 
                        onClick={() => { 
                          setTagBufList(tagBufList.filter(t => t !== tag))
                          setPage(1)
                        }}
                        className="text-green-600 hover:text-green-800"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 削弱标签 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <select className="select flex-1" value="" onChange={e => {
                  if (e.target.value && !tagDebList.includes(e.target.value)) {
                    setTagDebList([...tagDebList, e.target.value])
                    setPage(1)
                  }
                  e.target.value = ''
                }}>
                  <option value="">🔴 削弱 (+)</option>
                  {debCounts.filter(t => !tagDebList.includes(t.name)).map(t =>
                    <option key={t.name} value={t.name}>
                      {`${tagLabel(t.name)}（${t.count}）`}
                    </option>
                  )}
                </select>
                <select className="select w-20" value={tagDebMode} onChange={e => { setTagDebMode(e.target.value as 'all' | 'any'); setPage(1) }}>
                  <option value="all">AND</option>
                  <option value="any">OR</option>
                </select>
              </div>
              {tagDebList.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tagDebList.map(tag => (
                    <span key={tag} className="inline-flex items-center gap-1 px-2 py-1 bg-red-100 text-red-800 rounded text-sm">
                      🔴{tagLabel(tag)}
                      <button 
                        onClick={() => { 
                          setTagDebList(tagDebList.filter(t => t !== tag))
                          setPage(1)
                        }}
                        className="text-red-600 hover:text-red-800"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 特殊标签 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <select className="select flex-1" value="" onChange={e => {
                  if (e.target.value && !tagUtilList.includes(e.target.value)) {
                    setTagUtilList([...tagUtilList, e.target.value])
                    setPage(1)
                  }
                  e.target.value = ''
                }}>
                  <option value="">🟣 特殊 (+)</option>
                  {utilCounts.filter(t => !tagUtilList.includes(t.name)).map(t =>
                    <option key={t.name} value={t.name}>
                      {`${tagLabel(t.name)}（${t.count}）`}
                    </option>
                  )}
                </select>
                <select className="select w-20" value={tagUtilMode} onChange={e => { setTagUtilMode(e.target.value as 'all' | 'any'); setPage(1) }}>
                  <option value="all">AND</option>
                  <option value="any">OR</option>
                </select>
              </div>
              {tagUtilList.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {tagUtilList.map(tag => (
                    <span key={tag} className="inline-flex items-center gap-1 px-2 py-1 bg-purple-100 text-purple-800 rounded text-sm">
                      🟣{tagLabel(tag)}
                      <button 
                        onClick={() => { 
                          setTagUtilList(tagUtilList.filter(t => t !== tag))
                          setPage(1)
                        }}
                        className="text-purple-600 hover:text-purple-800"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 统计栏（保持原样） */}
      <div className="card p-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">仓库妖怪数量</div>
            <div className="text-xl font-semibold">
              {typeof wstats.data?.owned_total === 'number'
                  ? wstats.data.owned_total
                  : (typeof wstats.data?.in_warehouse === 'number' ? wstats.data.in_warehouse : '—')}
            </div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">总数</div>
            <div className="text-xl font-semibold">{stats.data?.total ?? '—'}</div>
          </div>
        </div>
      </div>

      {/* 批量操作条 */}
      {selectedIds.size > 0 && (
        <div className="card p-3 flex items-center justify-between">
          <div className="text-sm text-gray-600">已选 {selectedIds.size} 项</div>
          <div className="flex items-center gap-2">
            <button className={`btn ${BTN_FX}`} onClick={() => setSelectedIds(new Set())}>清除选择</button>
            <button className={`btn ${BTN_FX}`} onClick={() => bulkSetWarehouse(true)}>加入仓库</button>
            <button className={`btn ${BTN_FX}`} onClick={() => bulkSetWarehouse(false)}>移出仓库</button>
            {/* 新增：加入收藏 */}
            <button
              className={`btn ${BTN_FX}`}
              onClick={openAddToCollection}
              disabled={selectedIds.size === 0}
              title={selectedIds.size === 0 ? '勾选一些后再加入收藏' : '加入收藏分组'}
            >
              加入收藏
            </button>
            {/* 新增：从当前收藏组移除（仅当已选择收藏组时显示） */}
            {collectionId && selectedIds.size > 0 && (
              <button
                className={`btn ${BTN_FX}`}
                onClick={removeSelectedFromCollection}
                title="从当前收藏组移除选中的妖怪"
              >
                从收藏移除
              </button>
            )}
            <button className={`btn btn-primary ${BTN_FX}`} onClick={bulkDelete}>批量删除</button>
          </div>
        </div>
      )}

      {/* 列表/卡片视图 */}
      <div className="card">
        <div className="p-3">
          {view === 'card' ? (
            <>
              {list.isLoading ? (
                <SkeletonCardGrid />
              ) : (
                <MonsterCardGrid
                  items={filteredItems as Monster[]}
                  selectedIds={selectedIds}
                  onToggleSelect={toggleOne}
                  onOpenDetail={openDetail}
                  showRawSummary={true}
                  computeRibbon={computeRibbon}
                />
              )}
            </>
          ) : (
            <div className="overflow-auto">
              <table className="table table-auto table-zebra">
                <thead>
                  <tr>
                    <th className="w-10 text-center">
                      <input
                        type="checkbox"
                        className="h-5 w-5"
                        checked={allVisibleSelected}
                        onChange={toggleAllVisible}
                        aria-label="全选本页可见项"
                      />
                    </th>
                    <th className="w-16 text-center">ID</th>
                    <th className="text-left">名称</th>
                    <th className="w-20 min-w-[64px] text-center">元素</th>
                    {/* ✅ 原始六维表头 */}
                    {STAT_COLS.map(col => (
                      <th key={col.key} className="w-14 text-center">{col.label}</th>
                    ))}
                    <th className="text-center">增强</th>
                    <th className="text-center">削弱</th>
                    <th className="text-center">特殊</th>
                  </tr>
                </thead>
                {list.isLoading && <SkeletonRows rows={8} cols={totalCols} />}
                {!list.isLoading && (
                  <tbody>
                    {filteredItems.map((m: any) => {
                      const buckets = bucketizeTags(m.tags)
                      const chips = (arr: string[], prefixEmoji: string) =>
                        arr.slice(0, LIMIT_TAGS_PER_CELL).map(t => <span key={t} className="badge">{prefixEmoji}{tagLabel(t)}</span>)
                      return (
                        <tr
                          key={m.id}
                          className="align-middle cursor-pointer hover:bg-gray-50"
                          onClick={() => openDetail(m)}
                          title=""
                        >
                          <td className="text-center align-middle py-2.5" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              className="h-5 w-5"
                              checked={selectedIds.has(m.id)}
                              onChange={() => toggleOne(m.id)}
                              aria-label={`选择 ${m.name || m.name_final}`}
                            />
                          </td>
                          <td className="text-center align-middle py-2.5">{m.id}</td>
                          <td className="text-left align-middle py-2.5 truncate max-w-[240px]" title={m.name || m.name_final}>
                            {m.name || m.name_final}
                          </td>
                          <td className="text-center align-middle py-2.5 whitespace-nowrap break-keep" title={m.element}>
                            {m.element}
                          </td>
                          {/* Raw stats only */}
                          {STAT_COLS.map(col => {
                            const val = (m as any)[col.key] ?? 0
                            return (
                              <td key={col.key} className="text-center align-middle py-2.5">{val}</td>
                            )
                          })}

                          <td className="text-center align-middle py-2.5">
                            <div className="inline-flex flex-wrap gap-1 justify-center">
                              {chips(buckets.buf, '🟢')}
                            </div>
                          </td>
                          <td className="text-center align-middle py-2.5">
                            <div className="inline-flex flex-wrap gap-1 justify-center">
                              {chips(buckets.deb, '🔴')}
                            </div>
                          </td>
                          <td className="text-center align-middle py-2.5">
                            <div className="inline-flex flex-wrap gap-1 justify-center">
                              {chips(buckets.util, '🟣')}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                    {filteredItems.length === 0 && (
                      <tr>
                        <td colSpan={totalCols} className="text-center text-gray-500 py-6">没有数据。请调整筛选或导入 JSON。</td>
                      </tr>
                    )}
                  </tbody>
                )}
              </table>
            </div>
          )}
          <div className="mt-3 flex items-center justify-end gap-2">
            <button className={`btn ${BTN_FX}`} onClick={() => setPage(1)}>返回第一页</button>
            <Pagination page={page} pageSize={pageSize} total={list.data?.total || 0} onPageChange={setPage} />
          </div>
        </div>
      </div>

      {/* 详情抽屉 */}
      <SideDrawer open={!!selected} onClose={() => { setSelected(null); setIsEditing(false); setIsCreating(false); setRawText('') }} title={isCreating ? '新增妖怪' : ((selected as any)?.name || (selected as any)?.name_final)}>
        {selected && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-end gap-2">
              {!isEditing ? (
                <>
                  <span className="text-sm text-gray-600 mr-auto">
                    {(selected as any)?.new_type === true && <span className="badge badge-success mr-2">可获取</span>}
                    {(selected as any)?.new_type === false && <span className="badge badge-warning mr-2">暂不可</span>}
                    {(selected as any)?.possess && <span className="badge badge-info">已拥有</span>}
                  </span>
                  <button className={`btn ${BTN_FX}`} onClick={enterEdit}>编辑</button>
                  <button className={`btn ${BTN_FX}`} onClick={() => deleteOne((selected as any).id)}>删除</button>
                </>
              ) : (
                <>
                  <button className={`btn ${BTN_FX}`} onClick={cancelEdit}>取消</button>
                  <button className={`btn btn-primary ${BTN_FX}`} onClick={isCreating ? saveCreate : saveEdit} disabled={saving}>
                    {saving ? '保存中…' : '保存'}
                  </button>
                </>
              )}
            </div>

            {isEditing ? (
              <>
                {/* 识别链接框（仅编辑态显示；新增和编辑都可用） */}
                <div className="card p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">识别链接（自动爬取并填充）</h4>
                    <button className={`btn ${BTN_FX}`} onClick={recognizeAndPrefillFromLinks} disabled={recognizing}>
                      {recognizing ? '识别中…' : '识别并填充'}
                    </button>
                  </div>
                  <textarea
                    className="input h-32"
                    placeholder="将 4399 图鉴详情页链接粘贴到这里（可混在一段文字里；支持多条，默认取第 1 条）&#10;&#10;示例URL格式：&#10;https://news.4399.com/kabuxiyou/yaoguaidaquan/yaoxi/202509-19-1006841.html&#10;&#10;注意：请使用最新的图鉴详情页URL，旧格式链接可能无法解析"
                    value={rawText}
                    onChange={e => setRawText(e.target.value)}
                  />
                </div>

                {/* 基础信息编辑 */}
                <div className="card p-3 space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="md:col-span-2">
                      <label className="label">名称</label>
                      <input className="input" value={editName} onChange={e => setEditName(e.target.value)} />
                    </div>
                    <div>
                      <label className="label">元素</label>
                      <select className="select" value={editElement} onChange={e => setEditElement(e.target.value)}>
                        <option value="">未设置</option>
                        {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
                      </select>
                    </div>


                    {/* 获取渠道 / 获取方式 */}
                    <div>
                      <label className="label">获取渠道</label>
                      <select className="select" value={editType} onChange={e => setEditType(e.target.value)}>
                        <option value="">未设置</option>
                        {acquireTypeOptions.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                    <div className="md:col-span-2">
                      <label className="label">获取方式（可填原文/说明）</label>
                      <textarea className="input h-24" value={editMethod} onChange={e => setEditMethod(e.target.value)} placeholder="示例：2025年8月1日起，在青龙山探索捕获灯碟碟" />
                    </div>

                    <div className="md:col-span-2">
                      <TagSelector
                        value={editTags}
                        onChange={setEditTags}
                        monsterId={selected?.id}
                        className="w-full"
                      />
                    </div>
                  </div>
                </div>


                {/* 技能：卡片编辑，紧凑布局 */}
                <div className="card p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">技能</h4>
                    <button className={`btn ${BTN_FX}`} onClick={addSkill}>+ 新增技能</button>
                  </div>
                  
                  {/* 推荐技能快捷操作 */}
                  {editSkills.length > 0 && (
                    <SkillRecommendationHelper
                      skills={editSkills}
                      onUpdateSkills={setEditSkills}
                    />
                  )}
                  
                  <ul className="space-y-3">
                    {editSkills.map((s, idx) => (
                      <li key={idx} className="p-3 bg-gray-50 rounded">
                        <div className="flex items-start gap-3">
                          <div className="flex-1 space-y-3">
                            {/* 技能名和推荐状态 */}
                            <div className="flex items-center gap-3">
                              <div className="flex-1">
                                <label className="label">技能名</label>
                                <input className="input" value={s.name} onChange={e => updateSkill(idx, { name: e.target.value })} />
                              </div>
                              <div className="flex items-center gap-2 mt-6">
                                <input 
                                  type="checkbox" 
                                  id={`skill-selected-${idx}`}
                                  checked={s.selected || false}
                                  onChange={e => updateSkill(idx, { selected: e.target.checked })}
                                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                                />
                                <label htmlFor={`skill-selected-${idx}`} className="text-sm font-medium text-blue-700">
                                  {s.selected ? '★ 推荐' : '推荐'}
                                </label>
                              </div>
                            </div>
                            
                            {/* 元素、种类、威力、PP - 紧凑布局 */}
                            <div className="grid grid-cols-4 gap-2">
                              <div>
                                <label className="label text-xs">元素</label>
                                <select className="select text-sm" value={s.element || ''} onChange={e => updateSkill(idx, { element: e.target.value })}>
                                  <option value="">未设置</option>
                                  {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
                                </select>
                              </div>
                              <div>
                                <label className="label text-xs">种类</label>
                                <input className="input text-sm" placeholder="物理/法术/辅助" value={s.kind || ''} onChange={e => updateSkill(idx, { kind: e.target.value })} />
                              </div>
                              <div>
                                <label className="label text-xs">威力</label>
                                <input className="input text-sm" type="number" placeholder="145" value={(s.power ?? '') as any}
                                       onChange={e => updateSkill(idx, { power: e.target.value === '' ? null : Number(e.target.value) })} />
                              </div>
                              <div>
                                <label className="label text-xs">PP</label>
                                <input className="input text-sm" type="number" placeholder="20" value={(s.pp ?? '') as any}
                                       onChange={e => updateSkill(idx, { pp: e.target.value === '' ? null : Number(e.target.value) })} />
                              </div>
                            </div>
                            
                            {/* 描述 */}
                            <div>
                              <label className="label text-xs">描述</label>
                              <textarea className="input h-10 text-sm" value={s.description || ''} onChange={e => updateSkill(idx, { description: e.target.value })} />
                            </div>
                          </div>

                          {/* 右侧操作区域 - 更紧凑 */}
                          <div className="w-16 flex flex-col items-center shrink-0">
                            <div className="text-[10px] text-gray-400 text-center mb-1">
                              #{idx + 1}
                            </div>
                            {s.selected && (
                              <div className="w-2 h-2 bg-blue-500 rounded-full mb-2" title="推荐技能"></div>
                            )}
                            <button 
                              className="w-8 h-8 bg-red-500 hover:bg-red-600 text-white rounded text-xs flex items-center justify-center transition-colors" 
                              onClick={() => removeSkill(idx)}
                              title="删除技能"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                  <div className="text-xs text-gray-500">
                    保存时会逐条写入；留空或无效的技能名将被忽略。
                  </div>
                </div>
              </>
            ) : (
              <>
                {/* 获取方式/渠道展示 */}
                <div className="card p-3 space-y-2">
                  <div className="text-sm text-gray-600">获取渠道：{(selected as any)?.type || '—'}</div>
                  <div className="text-sm text-gray-600">获取方式：</div>
                  <div className="text-sm whitespace-pre-wrap">{(selected as any)?.method || '—'}</div>
                  <div className="text-xs text-gray-400">
                    创建：{(selected as any)?.created_at || '—'}，更新：{(selected as any)?.updated_at || '—'}
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold mb-2">基础种族值（原始六维）</h4>
                  <MonsterStatsRadar 
                    monster={selected} 
                    className="mt-2"
                  />
                </div>


                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-semibold">技能</h4>
                    <button 
                      className={`btn text-xs ${showAllSkills ? 'btn-primary' : ''}`} 
                      onClick={() => setShowAllSkills(!showAllSkills)}
                    >
                      {showAllSkills ? '只显示推荐' : '显示全部'}
                    </button>
                  </div>
                  {skills.isLoading && <div className="text-sm text-gray-500">加载中...</div>}
                  {!skills.data?.length && !skills.isLoading &&
                      <div className="text-sm text-gray-500">暂无技能数据</div>}
                  <ul className="space-y-2">
                    {skills.data?.filter(s => {
                      if (!isValidSkillName(s.name)) return false;
                      return showAllSkills || s.selected === true;
                    }).map(s => (
                        <li key={`${s.id || s.name}`} className={`p-3 rounded ${s.selected ? 'bg-blue-50 border border-blue-200' : 'bg-gray-50'}`}>
                          <div className="flex items-center justify-between">
                            <div className="font-medium">
                              {s.selected && <span className="text-blue-600 text-xs mr-1">⭐</span>}
                              {s.name}
                            </div>
                            <div className="text-xs text-gray-500">
                              {[s.element, s.kind, (s.power ?? '')].filter(Boolean).join(' / ') || '—'}
                          </div>
                        </div>
                        {isMeaningfulDesc(s.description) && (
                          <div className="text-sm text-gray-600 whitespace-pre-wrap mt-1">{s.description}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* 标签分三类展示 */}
                <div>
                  <h4 className="font-semibold mb-2">标签</h4>
                  {(() => {
                    const b = bucketizeTags((selected as any).tags)
                    return (
                      <div className="space-y-2">
                        <div>
                          <div className="text-xs text-gray-500 mb-1">增强类</div>
                          <div className="flex flex-wrap gap-1">
                            {b.buf.length ? b.buf.map(t => <span key={t} className="badge">🟢{tagLabel(t)}</span>) : <span className="text-xs text-gray-400">（无）</span>}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500 mb-1">削弱类</div>
                          <div className="flex flex-wrap gap-1">
                            {b.deb.length ? b.deb.map(t => <span key={t} className="badge">🔴{tagLabel(t)}</span>) : <span className="text-xs text-gray-400">（无）</span>}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500 mb-1">特殊类</div>
                          <div className="flex flex-wrap gap-1">
                            {b.util.length ? b.util.map(t => <span key={t} className="badge">🟣{tagLabel(t)}</span>) : <span className="text-xs text-gray-400">（无）</span>}
                          </div>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </>
            )}
          </div>
        )}
      </SideDrawer>

      {/* 全屏模糊等待弹框：支持“确定进度”和“未知进度”两种 + 取消按钮（增加最短显示 + 柔和淡出） */}
      {overlay.show && (
        <div
          className={`fixed inset-0 z-50 backdrop-blur-sm bg-black/20 flex items-center justify-center
                      transition-opacity duration-500 ${overlay.closing ? 'opacity-0' : 'opacity-100'}`}
        >
          <div
            className={`rounded-2xl bg-white shadow-xl p-6 w-[min(92vw,420px)] text-center space-y-3
                        transition-all duration-500 ${overlay.closing ? 'opacity-0 scale-95' : 'opacity-100 scale-100'}`}
          >
            <div className="text-2xl">🐱</div>
            <div className="text-lg font-semibold">{overlay.title || '处理中…'}</div>
            <div className="text-sm text-gray-600">{overlay.sub || '请稍候~'}</div>

            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              {typeof progressPct === 'number' ? (
                <div className="h-2 bg-purple-300 rounded-full transition-all duration-200" style={{ width: `${progressPct}%` }} />
              ) : (
                <div className="h-2 w-1/2 animate-pulse bg-purple-300 rounded-full" />
              )}
            </div>

            {typeof progressPct === 'number' && (
              <div className="text-xs text-gray-500">
                {overlay.done}/{overlay.total}（成功 {overlay.ok}，失败 {overlay.fail}） — {progressPct}%
              </div>
            )}

            {overlay.cancelable && (
              <div className="pt-1">
                <button
                  className={`btn ${BTN_FX}`}
                  onClick={async () => {
                    // 立即显示取消状态
                    setOverlay(prev => ({ ...prev, sub: '正在取消当前任务…', cancelable: false }))
                    
                    // 异步调用后台取消API（不等待结果）
                    if (currentJobIdRef.current) {
                      try {
                        api.post(`/tags/ai_batch/${currentJobIdRef.current}/cancel`)
                      } catch {}
                    }
                    
                    // 2秒后直接关闭弹窗
                    setTimeout(() => {
                      if (cancelResolveRef.current) {
                        cancelResolveRef.current()
                        setTimeout(() => smoothCloseOverlay(), 100)
                      }
                    }, 2000)
                  }}
                >
                  取消
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 简易的“加入收藏”选择/新建弹框 */}
      {collectionDialogOpen && (
        <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center">
          <div className="bg-white rounded-2xl shadow-xl w-[min(92vw,520px)] p-5 space-y-4">
            <div className="text-lg font-semibold">加入收藏</div>

            <div className="space-y-3">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="col-mode"
                  className="h-4 w-4"
                  checked={collectionForm.mode === 'existing'}
                  onChange={() => setCollectionForm(s => ({ ...s, mode: 'existing' }))}
                />
                <span>选择已有分组</span>
              </label>
              <select
                className="select w-full"
                disabled={collectionForm.mode !== 'existing'}
                value={collectionForm.selectedId}
                onChange={e => setCollectionForm(s => ({ ...s, selectedId: e.target.value }))}
              >
                <option value="">请选择分组</option>
                {collections.data?.map((c: any) => (
                  <option key={c.id} value={String(c.id)}>{c.name}{typeof c.items_count === 'number' ? `（${c.items_count}）` : ''}</option>
                ))}
              </select>
            </div>

            <div className="space-y-3">
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="col-mode"
                  className="h-4 w-4"
                  checked={collectionForm.mode === 'new'}
                  onChange={() => setCollectionForm(s => ({ ...s, mode: 'new' }))}
                />
                <span>新建分组</span>
              </label>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <input
                  className="input md:col-span-2"
                  placeholder="分组名称（必填）"
                  disabled={collectionForm.mode !== 'new'}
                  value={collectionForm.name}
                  onChange={e => setCollectionForm(s => ({ ...s, name: e.target.value }))}
                />
                <input
                  className="input"
                  placeholder="颜色（可选）"
                  disabled={collectionForm.mode !== 'new'}
                  value={collectionForm.color}
                  onChange={e => setCollectionForm(s => ({ ...s, color: e.target.value }))}
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <button className={`btn ${BTN_FX}`} onClick={() => { setCollectionDialogOpen(false); setCollectionForm({ mode: 'existing', selectedId: '', name: '', color: '' }) }}>
                取消
              </button>
              <button className={`btn btn-primary ${BTN_FX}`} onClick={submitAddToCollection}>
                确定
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 简洁爬取创建弹框 */}
      <Modal open={crawlDialogOpen} onClose={() => { setCrawlDialogOpen(false); setCrawlUrl('') }}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">新增妖怪</h2>
          <button 
            className="btn" 
            onClick={() => {
              setCrawlDialogOpen(false)
              setCrawlUrl('')
            }}
            disabled={crawling}
          >
            关闭
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label">妖怪详情页链接</label>
            <input
              className="input"
              placeholder="请粘贴4399图鉴详情页链接..."
              value={crawlUrl}
              onChange={e => setCrawlUrl(e.target.value)}
              disabled={crawling}
            />
            <div className="text-xs text-gray-500 mt-1">
              示例：https://news.4399.com/kabuxiyou/yaoguaidaquan/huanxi/202509-19-1006841.html
            </div>
          </div>
        </div>

        <div className="pt-2 flex justify-end gap-2">
          <button 
            className="btn" 
            onClick={() => {
              setCrawlDialogOpen(false)
              setCrawlUrl('')
            }}
            disabled={crawling}
          >
            取消
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleCrawlAndCreate}
            disabled={crawling || !crawlUrl.trim()}
          >
            {crawling ? '爬取中...' : '自动爬取并创建'}
          </button>
        </div>
      </Modal>
    </div>
  )
}