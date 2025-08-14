// client/src/pages/MonstersPage.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import SideDrawer from '../components/SideDrawer'

type RoleCount = { name: string, count: number }

// 适配新后端：技能带 element/kind/power/description
type SkillDTO = {
  id?: number
  name: string
  element?: string | null
  kind?: string | null
  power?: number | null
  description?: string
}

type StatsDTO = { total: number; with_skills?: number; tags_total?: number }
type WarehouseStatsDTO = { warehouse_total?: number; total?: number }

type SortKey = 'updated_at' | 'offense' | 'survive' | 'control' | 'tempo' | 'pp_pressure'

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

// —— 完整元素映射（code -> 中文），以及选项数组 —— //
const ELEMENTS: Record<string, string> = {
  huoxi: '火系', jinxi: '金系', muxi: '木系', shuixi: '水系', tuxi: '土系', yixi: '翼系',
  guaixi: '怪系', moxi: '魔系', yaoxi: '妖系', fengxi: '风系', duxi: '毒系', leixi: '雷系',
  huanxi: '幻系', bing: '冰系', lingxi: '灵系', jixie: '机械', huofengxi: '火风系',
  mulingxi: '木灵系', tuhuanxi: '土幻系', shuiyaoxi: '水妖系', yinxi: '音系', shengxi: '圣系',
}
const elementOptionsFull = Array.from(new Set(Object.values(ELEMENTS)))

// —— 元素简称（技能属性）到中文元素映射 —— //
const SHORT_ELEMENT_TO_LABEL: Record<string, string> = {
  火: '火系', 水: '水系', 风: '风系', 雷: '雷系', 冰: '冰系', 木: '木系',
  土: '土系', 金: '金系', 圣: '圣系', 毒: '毒系', 幻: '幻系', 灵: '灵系',
  妖: '妖系', 魔: '魔系', 音: '音系', 机械: '机械', 特殊: '' // “特殊”不当作元素
}

export default function MonstersPage() {
  // 搜索 + 筛选
  const [q, setQ] = useState('')
  const [element, setElement] = useState('')           // 元素筛选（中文）
  const [acqType, setAcqType] = useState('')           // 获取途径

  // 三组标签（替代原单一 tag）
  const [tagBuf, setTagBuf] = useState('')
  const [tagDeb, setTagDeb] = useState('')
  const [tagUtil, setTagUtil] = useState('')
  const selectedTags = useMemo(() => [tagBuf, tagDeb, tagUtil].filter(Boolean) as string[], [tagBuf, tagDeb, tagUtil])

  const [role, setRole] = useState('')
  const [sort, setSort] = useState<SortKey>('updated_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [warehouseOnly, setWarehouseOnly] = useState(false) // 仅看仓库
  const [onlyGettable, setOnlyGettable] = useState(false)   // 仅显示可获得妖怪（new_type=true）

  // “修复妖怪”筛选（当前页：技能数为 0 或 >5）
  const [fixMode, setFixMode] = useState(false)
  const [fixLoading, setFixLoading] = useState(false)
  const [skillCountMap, setSkillCountMap] = useState<Record<number, number>>({})

  // 分页
  const [page, setPage] = useState(1)
  const pageSize = 20

  // 勾选/批量
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // 详情 & 编辑
  const [selected, setSelected] = useState<Monster | any | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editElement, setEditElement] = useState('')
  const [editRole, setEditRole] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editPossess, setEditPossess] = useState<boolean>(false)
  const [editGettable, setEditGettable] = useState<boolean>(false)
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

  const [saving, setSaving] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)

  // —— 新增模式 & 识别粘贴框 —— //
  const [isCreating, setIsCreating] = useState<boolean>(false)
  const [rawText, setRawText] = useState<string>('')
  const [createPreferredName, setCreatePreferredName] = useState<string>('')

  // 全屏模糊等待弹框 + 真实进度
  const [overlay, setOverlay] = useState<{
    show: boolean
    title?: string
    sub?: string
    total?: number
    done?: number
    ok?: number
    fail?: number
  }>({ show: false })

  // —— 一键爬取 —— //
  const [crawling, setCrawling] = useState(false)
  const [crawlLimit, setCrawlLimit] = useState<string>('')

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

  const list = useQuery({
    queryKey: ['monsters', {
      q, element, tagBuf, tagDeb, tagUtil, role, acqType, sort, order, page, pageSize, warehouseOnly, onlyGettable
    }],
    queryFn: async () => {
      const endpoint = warehouseOnly ? '/warehouse' : '/monsters'
      const params: any = {
        q: q || undefined,
        element: element || undefined,
        role: role || undefined,
        // 获取途径多口径
        type: acqType || undefined,
        acq_type: acqType || undefined,
        acquire_type: acqType || undefined,
        type_contains: acqType || undefined,
        new_type: onlyGettable ? true : undefined,
        sort, order, page, page_size: pageSize,
      }
      if (selectedTags.length >= 2) params.tags_all = selectedTags
      else if (selectedTags.length === 1) params.tag = selectedTags[0]

      return (await api.get(endpoint, { params })).data as MonsterListResp
    }
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

  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      try {
        return (await api.get('/roles')).data as RoleCount[]
      } catch {
        return [] as RoleCount[]
      }
    }
  })

  // 总数
  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get('/stats')).data as StatsDTO
  })
  // 仓库数量（严格以 /warehouse 的 total 为准）
  const wstats = useQuery({
    queryKey: ['warehouse_stats_total_only'],
    queryFn: async () => {
      const d = (await api.get('/warehouse', { params: { page: 1, page_size: 1 } })).data as MonsterListResp
      return { warehouse_total: d?.total ?? 0 } as WarehouseStatsDTO
    }
  })

  const skills = useQuery({
    queryKey: ['skills', (selected as any)?.id],
    enabled: !!(selected as any)?.id,
    queryFn: async () => (await api.get(`/monsters/${(selected as any)!.id}/skills`)).data as SkillDTO[]
  })

  // —— 当前页“修复妖怪”需要的技能计数 —— //
  useEffect(() => {
    let stopped = false
    const load = async () => {
      if (!fixMode) return
      const items = (list.data?.items as any[]) || []
      if (!items.length) { setSkillCountMap({}); return }
      setFixLoading(true)
      try {
        const pairs = await Promise.all(
          items.map(async (m: any) => {
            try {
              const r = await api.get(`/monsters/${m.id}/skills`)
              const cnt = ((r.data as SkillDTO[]) || []).filter(s => isValidSkillName(s.name)).length
              return [m.id, cnt] as [number, number]
            } catch {
              return [m.id, 0] as [number, number]
            }
          })
        )
        if (stopped) return
        const map: Record<number, number> = {}
        pairs.forEach(([id, c]) => { map[id] = c })
        setSkillCountMap(map)
      } finally {
        if (!stopped) setFixLoading(false)
      }
    }
    load()
    return () => { stopped = true }
  }, [fixMode, list.data, page])

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
    const ids = (list.data?.items as any[])?.map(i => i.id) || []
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

  // —— 导入/导出/备份/恢复 —— //
  const importCSVInputRef = useRef<HTMLInputElement>(null)
  const restoreInputRef = useRef<HTMLInputElement>(null)

  const openImportCSV = () => importCSVInputRef.current?.click()
  const onImportCSVFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    try {
      try {
        await api.post('/api/v1/import/monsters_csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      } catch {
        try {
          await api.post('/import/monsters_csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        } catch {
          await api.post('/import/monsters.csv', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        }
      }
      alert('CSV 导入完成！')
      list.refetch(); stats.refetch(); wstats.refetch()
    } catch (err: any) {
      alert('CSV 导入失败：' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      e.target.value = ''
    }
  }

  const exportCSV = async () => {
    const params: any = {
      q: q || undefined, element: element || undefined, role: role || undefined,
      type: acqType || undefined, acq_type: acqType || undefined,
      new_type: onlyGettable ? true : undefined, sort, order
    }
    if (selectedTags.length >= 2) params.tags_all = selectedTags
    else if (selectedTags.length === 1) params.tag = selectedTags[0]

    const res = await api.get('/export/monsters.csv', { params, responseType: 'blob' })
    const url = window.URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url; a.download = `monsters_${Date.now()}.csv`; a.click()
    window.URL.revokeObjectURL(url)
  }
  const exportBackup = async () => {
    const res = await api.get('/backup/export_json', { responseType: 'blob' })
    const url = window.URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url; a.download = `backup_${Date.now()}.json`; a.click()
    window.URL.revokeObjectURL(url)
  }
  const openRestore = () => restoreInputRef.current?.click()
  const onRestoreFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    try {
      const text = await f.text()
      const json = JSON.parse(text)
      await api.post('/backup/restore_json', json)
      alert('恢复完成！')
      list.refetch(); stats.refetch(); wstats.refetch()
    } catch (err: any) {
      alert('恢复失败：' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      e.target.value = ''
    }
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
    setEditPossess(!!s.possess)
    setEditGettable(!!s.new_type)
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
        description: x.description ?? ''
      }))
    setEditSkills(rows.length ? rows : [{ name: '', element: '', kind: '', power: null, description: '' }])

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
          power, // ← 不再和 '' 比较
          description: (s.description || '').trim(),
        }
      })
  .filter(s => isValidSkillName(s.name))
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
        return o
      })

    // 2) 新接口：PUT + 裸数组（你的后端签名就是 List[SkillIn]）
    try {
      return await api.put(`/monsters/${monsterId}/skills`, skills, {
        headers: { 'Content-Type': 'application/json' }
      })
    } catch (e1: any) {
      // 3) 老接口兜底（尽量不走，会引发老逻辑的重复名问题）
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
        possess: !!editPossess,
        new_type: !!editGettable,
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
        role: editRole || null,
        possess: !!editPossess,
        new_type: !!editGettable,
        type: editType || null,
        method: editMethod || null,
        hp, speed, attack, defense, magic, resist,
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))),
      }

      let res
      try {
        res = await api.post('/monsters', body)
      } catch (e1) {
        try {
          res = await api.post('/api/v1/monsters', body)
        } catch (e2) {
          alert('当前后端未开放创建接口，请改用 CSV/JSON 导入或开启 /monsters 创建 API。')
          return
        }
      }

      const newId = res?.data?.id ?? res?.data?.monster?.id ?? res?.data?.data?.id
      if (!newId) {
        alert('创建成功但未返回 ID，无法写入技能。')
      } else {
        await saveSkills(newId, editSkills)
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
          try { await api.get(`/monsters/${id}/derived`) } catch {}
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
    const endpoint = warehouseOnly ? '/warehouse' : '/monsters'
    const pageSizeFetch = 200
    let pageNo = 1
    let total = 0
    const ids: number[] = []
    while (true) {
      const params: any = {
        q: q || undefined,
        element: element || undefined,
        role: role || undefined,
        type: acqType || undefined,
        acq_type: acqType || undefined,
        new_type: onlyGettable ? true : undefined,
        sort, order,
        page: pageNo,
        page_size: pageSizeFetch
      }
      if (selectedTags.length >= 2) params.tags_all = selectedTags
      else if (selectedTags.length === 1) params.tag = selectedTags[0]

      const resp = await api.get(endpoint, { params })
      const data = resp.data as MonsterListResp
      const arr = (data.items as any[]) || []
      ids.push(...arr.map(x => x.id))
      total = data.total || ids.length
      if (arr.length === 0 || ids.length >= total) break
      pageNo += 1
    }
    return Array.from(new Set(ids))
  }

  // —— 一键 AI 打标签（真实进度版） —— //
  const aiTagBatch = async () => {
    let targetIds: number[] = selectedIds.size ? Array.from(selectedIds) : await collectAllTargetIds()
    if (!targetIds.length) return alert('当前没有可处理的记录')

    setOverlay({ show: true, title: 'AI 打标签进行中…', sub: '正在分析', total: targetIds.length, done: 0, ok: 0, fail: 0 })

    let okCount = 0
    let failCount = 0
    try {
      for (const id of targetIds) {
        try {
          try {
            await api.post(`/tags/monsters/${id}/retag_ai`)
          } catch {
            await api.post(`/tags/monsters/${id}/retag`)
          }
          okCount += 1
          setOverlay(prev => ({ ...prev, done: (prev.done || 0) + 1, ok: (prev.ok || 0) + 1 }))
        } catch {
          failCount += 1
          setOverlay(prev => ({ ...prev, done: (prev.done || 0) + 1, fail: (prev.fail || 0) + 1 }))
        }
      }

      await list.refetch()
      if (selected) {
        const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
        setSelected(fresh)
      }

      alert(`AI 打标签完成：共 ${targetIds.length} 条，成功 ${okCount}，失败 ${failCount}`)
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'AI 打标签失败')
    } finally {
      setOverlay({ show: false })
    }
  }

  // —— 一键全部派生（未勾选 → 全部；无需进度） —— //
  const deriveBatch = async () => {
    const items = (list.data?.items as any[]) || []
    const ids = selectedIds.size ? Array.from(selectedIds) : await collectAllTargetIds()
    if (!ids.length && !items.length) return alert('当前没有可处理的记录')

    const showOverlay = ids.length > 1
    if (showOverlay) setOverlay({ show: true, title: '派生计算中…', sub: '可爱的等等呦 (=^･ω･^=)' })
    try {
      try {
        await api.post('/api/v1/derived/batch', { ids: ids.length ? ids : undefined })
      } catch {
        try {
          await api.post('/derived/batch', { ids: ids.length ? ids : undefined })
        } catch {
          const fallbackIds = ids.length ? ids : (items.map(i => i.id) as number[])
          for (const id of fallbackIds) {
            try { await api.get(`/monsters/${id}/derived`) } catch {}
          }
        }
      }
      await list.refetch()
      if (selected) {
        const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
        setSelected(fresh)
      }
      alert('派生完成')
    } catch (e:any) {
      alert(e?.response?.data?.detail || '派生失败')
    } finally {
      if (showOverlay) setOverlay({ show: false })
    }
  }

  const elementOptions = elementOptionsFull
  const acquireTypeOptions = ['可捕捉宠物','BOSS宠物','活动获取宠物','兑换/商店','任务获取','超进化','其它']

  // —— 批量加入/移出仓库 —— //
  const bulkSetWarehouse = async (flag: boolean) => {
    if (!selectedIds.size) return
    const ids = Array.from(selectedIds)
    await api.post('/warehouse/bulk_set', { ids, possess: flag })
    clearSelection()
    list.refetch()
    wstats.refetch()
  }

  // 小工具：更新/增删技能
  const updateSkill = (idx: number, patch: Partial<SkillDTO>) => {
    setEditSkills(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s))
  }
  const removeSkill = (idx: number) => setEditSkills(prev => prev.filter((_, i) => i !== idx))
  const addSkill = () => setEditSkills(prev => [...prev, { name: '', element: '', kind: '', power: null, description: '' }])

  // 编辑态时，保证至少有一条空卡可写
  useEffect(() => {
    if (isEditing && editSkills.length === 0) {
      setEditSkills([{ name: '', element: '', kind: '', power: null, description: '' }])
    }
  }, [isEditing, editSkills.length])

  // 计算进度百分比
  const progressPct = overlay.total ? Math.floor(((overlay.done || 0) / overlay.total) * 100) : null

  // —— 列表前端兜底过滤（获取途径 + 多标签 AND + 修复妖怪） —— //
  const filteredItems = useMemo(() => {
    let arr = (list.data?.items as any[]) || []
    if (acqType) {
      arr = arr.filter(m => ((m?.type || '') as string).includes(acqType))
    }
    if (selectedTags.length > 0) {
      arr = arr.filter(m => {
        const set = new Set<string>((m.tags || []) as string[])
        return selectedTags.every(t => set.has(t))
      })
    }
    if (fixMode) {
      arr = arr.filter(m => {
        const c = skillCountMap[m.id]
        return typeof c === 'number' ? (c === 0 || c > 5) : false
      })
    }
    return arr
  }, [list.data, acqType, selectedTags, fixMode, skillCountMap])

  // —— 新建：初始化清空并打开编辑抽屉 —— //
  const startCreate = () => {
    setIsCreating(true)
    setSelected({ id: 0 })
    setRawText('')
    setCreatePreferredName('')
    setEditName('')
    setEditElement('')
    setEditRole('')
    setEditTags('')
    setEditPossess(false)
    setEditGettable(false)
    setEditType('')
    setEditMethod('')
    setHp(100); setSpeed(100); setAttack(100); setDefense(100); setMagic(100); setResist(100)
    setEditSkills([{ name: '', element: '', kind: '', power: null, description: '' }])
    setIsEditing(true)
  }

  // —— 识别：清洗与解析 —— //
  const normalizeText = (raw: string) => {
    return raw
      .replace(/\r/g, '\n')
      .replace(/[　\t]+/g, ' ')
      .replace(/[，]/g, '，')
      .replace(/[。]/g, '。')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }

  const parseAndPrefillFromText = (raw: string) => {
    const text = normalizeText(raw)
    if (!text) { alert('请先粘贴文本'); return }

    // 拆行（移除空行）
    const allLines = text.split('\n').map(s => s.trim()).filter(Boolean)

    // 1) 名称 + 六维（扫描形如：名字 6个数字）
    type StatRow = { name: string, nums: number[] }
    const statRows: StatRow[] = []
    const statRegex = /^([\u4e00-\u9fa5A-Za-z]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$/
    for (const ln of allLines) {
      const m = ln.match(statRegex)
      if (m) {
        const name = m[1]
        const nums = m.slice(2).map(x => parseInt(x, 10))
        if (nums.length === 6 && nums.every(n => Number.isFinite(n))) {
          statRows.push({ name, nums })
        }
      }
    }
    // 选名：默认第二个（高阶），否则第一个
    const chosen = statRows[1] || statRows[0]
    if (chosen) {
      setEditName(chosen.name)
      setCreatePreferredName(chosen.name)
      setHp(chosen.nums[0]); setSpeed(chosen.nums[1]); setAttack(chosen.nums[2]); setDefense(chosen.nums[3]); setMagic(chosen.nums[4]); setResist(chosen.nums[5])
    }

    // 2) 获得方式 / 渠道
    const idxAcquire = allLines.findIndex(l => l.includes('获得方式'))
    if (idxAcquire >= 0) {
      let method = allLines[idxAcquire].replace(/.*?获得方式/, '').trim()
      if (!method) method = allLines[idxAcquire + 1] || ''
      setEditMethod(method || '')
      // 渠道枚举匹配
      let typeGuess = ''
      const s = method
      if (/捕捉|可捕捉/.test(s)) typeGuess = '可捕捉宠物'
      else if (/BOSS/.test(s)) typeGuess = 'BOSS宠物'
      else if (/活动|VIP|年费|礼包|节日/.test(s)) typeGuess = '活动获取宠物'
      else if (/兑换|商店/.test(s)) typeGuess = '兑换/商店'
      else if (/任务/.test(s)) typeGuess = '任务获取'
      else if (/超进化/.test(s)) typeGuess = '超进化'
      else typeGuess = '其它'
      if (acquireTypeOptions.includes(typeGuess)) setEditType(typeGuess)
      if (/可获得|可捕捉|VIP可获得|年费/.test(s)) setEditGettable(true)
    }

    // 3) 技能表解析
    const idxTab = allLines.findIndex(l => l.includes('技能表'))
    let skillLines: string[] = []
    if (idxTab >= 0) {
      // 从“技能表”后开始，直到文本结束（或遇到明显的下一个模块关键词停止，这里简单取到结尾）
      const after = allLines.slice(idxTab + 1)
      // 跳过表头（包含“技能名称/等级/技能属性/类型/威力/PP/技能描述”）
      let start = 0
      for (let i = 0; i < after.length; i++) {
        if (!/技能名称|等级|技能属性|类型|威力|PP|技能描述/.test(after[i])) { start = i; break }
      }
      skillLines = after.slice(start)
    }

    // 将“断行的威力+PP+描述”合并到上一行（例如：... 特殊 法术 | 下一行：0 20 描述）
    const merged: string[] = []
    const partialRe = /^(\S+)\s+(\d+)\s+(圣|火|水|风|雷|冰|木|土|金|毒|幻|灵|妖|魔|音|机械|特殊)\s+(法术|物理|特殊)(?:\s+(\d+))?/
    for (let i = 0; i < skillLines.length; i++) {
      let ln = skillLines[i]
      const m = ln.match(partialRe)
      if (m && !/\s\d+\s+\d+\s+/.test(ln) && i + 1 < skillLines.length) {
        ln = (ln + ' ' + skillLines[i + 1]).trim()
        i += 1
      }
      merged.push(ln)
    }

    const rowRe = /^(\S+)\s+(\d+)\s+(圣|火|水|风|雷|冰|木|土|金|毒|幻|灵|妖|魔|音|机械|特殊)\s+(法术|物理|特殊)\s*(\d+)?\s*(\d+)?\s*(.*)$/
    const parsedSkills: SkillDTO[] = []
    for (const ln of merged) {
      const m = ln.match(rowRe)
      if (!m) continue
      const name = m[1]
      const attr = m[3]
      const kind = m[4]
      const powerStr = m[5]
      const desc = m[7] || ''
      if (!isValidSkillName(name)) continue
      const elementLabel = SHORT_ELEMENT_TO_LABEL[attr] ?? ''
      const pow = powerStr ? Number(powerStr) : NaN
      parsedSkills.push({
        name,
        element: elementLabel || '',
        kind,
        power: Number.isFinite(pow) ? (pow === 0 ? null : pow) : null,
        description: desc.trim()
      })
    }

    // 4) 满级配招 → 置顶
    const idxCombo = allLines.findIndex(l => l.includes('满级配招'))
    let recNames: string[] = []
    if (idxCombo >= 0) {
      const line = allLines[idxCombo].replace(/.*?满级配招/, '').trim()
      const next = allLines[idxCombo + 1] || ''
      const comboText = (line || next || '').replace(/[（）]/g, (m) => (m === '（' ? '(' : m === '）' ? ')' : m))
      const inside = (comboText.match(/\(([^)]*)\)/)?.[1] || '').split(/、|,|，|\s+/).map(s => s.trim()).filter(Boolean)
      const outside = comboText.replace(/\([^)]*\)/g, '').split(/、|,|，|\s+/).map(s => s.trim()).filter(Boolean)
      recNames = Array.from(new Set([...outside, ...inside])).filter(isValidSkillName)
    }

    // 将推荐配招排最前；没在表里的，用占位补上
    const byName = new Map<string, SkillDTO>()
    parsedSkills.forEach(s => byName.set(s.name, s))
    const prioritized: SkillDTO[] = []
    for (const nm of recNames) {
      if (byName.has(nm)) {
        prioritized.push(byName.get(nm)!)
        byName.delete(nm)
      } else {
        prioritized.push({ name: nm, element: '', kind: '', power: null, description: '' })
      }
    }
    const finalSkills = [...prioritized, ...Array.from(byName.values())]
    setEditSkills(finalSkills.length ? finalSkills : [{ name: '', element: '', kind: '', power: null, description: '' }])

    // 5) 通过技能主属性简单推断元素（若未填）
    if (!editElement) {
      const counts: Record<string, number> = {}
      for (const s of parsedSkills) {
        if (!s.element) continue
        counts[s.element] = (counts[s.element] || 0) + 1
      }
      const guess = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0]
      if (guess) setEditElement(guess)
    }

    alert('已识别并填充，可继续手动调整。')
  }

  return (
    <div className="container my-6 space-y-4">
      {/* 顶部工具栏 */}
      <div className="card p-4">
        {/* 0 行：导入/导出/备份/恢复（放最上方，紧邻“导入 CSV”一组） */}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <button className={`btn ${BTN_FX}`} onClick={openImportCSV}>导入 CSV</button>
            <button className={`btn ${BTN_FX}`} onClick={exportCSV}>导出 CSV</button>
            <button className={`btn ${BTN_FX}`} onClick={exportBackup}>备份 JSON</button>
            <button className={`btn ${BTN_FX}`} onClick={openRestore}>恢复 JSON</button>
            <input ref={importCSVInputRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onImportCSVFile} />
            <input id="restoreInput" ref={restoreInputRef} type="file" accept="application/json" className="hidden" onChange={onRestoreFile} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* 新增：修复妖怪（放在“一键 AI 打标签”左边） */}
            <button
              className={`btn ${BTN_FX} ${fixMode ? 'btn-primary' : ''}`}
              title="筛选出当前页中没有技能或技能数量大于 5 的妖怪"
              aria-pressed={fixMode}
              onClick={() => setFixMode(v => !v)}
              disabled={list.isLoading}
            >
              {fixMode ? (fixLoading ? '修复妖怪（筛选中…）' : '修复妖怪（已开启）') : '修复妖怪'}
            </button>

            <button className={`btn ${BTN_FX}`} onClick={aiTagBatch}>一键 AI 打标签</button>
            {/* 要求：一键全部派生按钮设为白色 */}
            <button className={`btn ${BTN_FX}`} onClick={deriveBatch}>一键全部派生</button>

            <button
              className={`btn btn-lg ${warehouseOnly ? 'btn-primary' : ''} ${BTN_FX}`}
              onClick={() => { setWarehouseOnly(v => !v); setPage(1) }}
              title="只显示仓库已有的宠物 / 再次点击还原"
            >
              仓库管理
            </button>
            <button
              className={`btn ${onlyGettable ? 'btn-primary' : ''} ${BTN_FX}`}
              onClick={() => { setOnlyGettable(v => !v); setPage(1) }}
              title="只显示当前可获得妖怪"
            >
              仅显示可获得妖怪
            </button>
            <button className={`btn ${BTN_FX}`} onClick={startCrawl} disabled={crawling}>
              {crawling ? '爬取中…' : '一键爬取图鉴'}
            </button>

            {/* 新增：新增妖怪 */}
            <button className={`btn btn-primary ${BTN_FX}`} onClick={startCreate}>新增妖怪</button>
          </div>
        </div>

        {/* 1 行：搜索与上限 —— 2 列等宽 */}
        <div className="mb-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0">
            <input
              className="input w-full min-w-0"
              placeholder="搜索名称 / 技能关键词…"
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              aria-label="搜索"
            />
            <input
              className="input w-full min-w-0"
              placeholder="抓取上限(可选)"
              value={crawlLimit}
              onChange={e => setCrawlLimit(e.target.value.replace(/[^\d]/g, ''))}
            />
          </div>
        </div>

        {/* 2 行：元素 + 获取途径 + 三组标签 + 定位 + 排序 */}
        <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
          <select className="select" value={element} onChange={e => { setElement(e.target.value); setPage(1) }}>
            <option value="">全部元素</option>
            {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
          </select>

          <select className="select" value={acqType} onChange={e => { setAcqType(e.target.value); setPage(1) }}>
            <option value="">获取途径</option>
            {acquireTypeOptions.map(t => <option key={t} value={t}>{t}</option>)}
          </select>

          {/* 三枚标签下拉 */}
          <select className="select" value={tagBuf} onChange={e => { setTagBuf(e.target.value); setPage(1) }}>
            <option value="">🟢 增强（全部）</option>
            {bufCounts.map(t =>
              <option key={t.name} value={t.name}>
                {`🟢${tagLabel(t.name)}（${t.count}）`}
              </option>
            )}
          </select>
          <select className="select" value={tagDeb} onChange={e => { setTagDeb(e.target.value); setPage(1) }}>
            <option value="">🔴 削弱（全部）</option>
            {debCounts.map(t =>
              <option key={t.name} value={t.name}>
                {`🔴${tagLabel(t.name)}（${t.count}）`}
              </option>
            )}
          </select>
          <select className="select" value={tagUtil} onChange={e => { setTagUtil(e.target.value); setPage(1) }}>
            <option value="">🟣 特殊（全部）</option>
            {utilCounts.map(t =>
              <option key={t.name} value={t.name}>
                {`🟣${tagLabel(t.name)}（${t.count}）`}
              </option>
            )}
          </select>

          <select className="select" value={role} onChange={e => { setRole(e.target.value); setPage(1) }}>
            <option value="">定位</option>
            {roles.data?.map(r => <option key={r.name} value={r.name}>{r.count ? `${r.name}（${r.count}）` : r.name}</option>)}
          </select>

          <div className="grid grid-cols-2 gap-3 col-span-2">
            <select
              className="select"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              <option value="updated_at">更新时间</option>
              <option value="offense">攻（派生）</option>
              <option value="survive">生（派生）</option>
              <option value="control">控（派生）</option>
              <option value="tempo">速（派生）</option>
              <option value="pp_pressure">压（派生）</option>
            </select>
            <select className="select" value={order} onChange={e => setOrder(e.target.value as any)}>
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
          </div>
        </div>
      </div>

      {/* 统计栏 */}
      <div className="card p-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">仓库妖怪数量</div>
            <div className="text-xl font-semibold">
              {typeof wstats.data?.warehouse_total === 'number' ? wstats.data.warehouse_total : '—'}
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
            <button className={`btn btn-primary ${BTN_FX}`} onClick={bulkDelete}>批量删除</button>
          </div>
        </div>
      )}

      {/* 列表 */}
      <div className="card">
        <div className="overflow-auto">
          <table className="table table-auto">
            <thead>
              <tr>
                <th className="w-10 text-center" />
                <th className="w-16 text-center">ID</th>
                <th className="text-left">名称</th>
                <th className="w-20 min-w-[64px] text-center">元素</th>
                <th className="w-20 text-center">定位</th>
                <th className="w-14 text-center">攻</th>
                <th className="w-14 text-center">生</th>
                <th className="w-14 text-center">控</th>
                <th className="w-14 text-center">速</th>
                <th className="w-14 text-center">压</th>
                <th className="text-center">增强</th>
                <th className="text-center">削弱</th>
                <th className="text-center">特殊</th>
              </tr>
            </thead>
            {list.isLoading && <SkeletonRows rows={8} cols={13} />}
            {!list.isLoading && (
              <tbody>
                {fixMode && fixLoading && (
                  <tr>
                    <td colSpan={13} className="text-center text-gray-500 py-4">正在根据技能数量筛选中…</td>
                  </tr>
                )}
                {!fixLoading && filteredItems.map((m: any) => {
                  const buckets = bucketizeTags(m.tags)
                  const chips = (arr: string[], prefixEmoji: string) =>
                    arr.slice(0, LIMIT_TAGS_PER_CELL).map(t => <span key={t} className="badge">{prefixEmoji}{tagLabel(t)}</span>)
                  return (
                    <tr key={m.id} className="align-middle">
                      <td className="text-center align-middle py-2.5">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(m.id)}
                          onChange={() => toggleOne(m.id)}
                          aria-label={`选择 ${m.name || m.name_final}`}
                        />
                      </td>
                      <td className="text-center align-middle py-2.5">{m.id}</td>
                      <td className="text-left align-middle py-2.5">
                        <button
                          className={`text-blue-600 hover:underline ${BTN_FX} truncate max-w-[240px]`}
                          title={m.name || m.name_final}
                          onClick={() => openDetail(m)}
                        >
                          {m.name || m.name_final}
                        </button>
                      </td>
                      <td className="text-center align-middle py-2.5 whitespace-nowrap break-keep" title={m.element}>
                        {m.element}
                      </td>
                      <td className="text-center align-middle py-2.5">{m.role || (m as any).derived?.role_suggested || ''}</td>
                      <td className="text-center align-middle py-2.5">{m.derived?.offense ?? 0}</td>
                      <td className="text-center align-middle py-2.5">{m.derived?.survive ?? 0}</td>
                      <td className="text-center align-middle py-2.5">{m.derived?.control ?? 0}</td>
                      <td className="text-center align-middle py-2.5">{m.derived?.tempo ?? 0}</td>
                      <td className="text-center align-middle py-2.5">{(m.derived as any)?.pp_pressure ?? 0}</td>
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
                {!fixLoading && filteredItems.length === 0 && (
                  <tr>
                    <td colSpan={13} className="text-center text-gray-500 py-6">没有数据。请调整筛选或导入 JSON/CSV。</td>
                  </tr>
                )}
              </tbody>
            )}
          </table>
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="text-sm text-gray-500">ETag: {list.data?.etag}</div>
          <div className="flex items-center gap-2">
            <button className={`btn ${BTN_FX}`} onClick={() => list.refetch()}>刷新</button>
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
                  <button className={`btn ${BTN_FX}`} onClick={async () => {
                    try { await api.get(`/monsters/${(selected as any).id}/derived`) } catch {}
                    enterEdit()
                  }}>编辑</button>
                  <button className={`btn ${BTN_FX}`} onClick={() => deleteOne((selected as any).id)}>删除</button>
                </>
              ) : (
                <>
                  {!isCreating && (
                    <button className={`btn ${BTN_FX}`} onClick={async () => {
                      // 抽屉内“填充”使用派生建议（仅编辑已有时）
                      const d = (await api.get(`/monsters/${(selected as any).id}/derived`)).data as {
                        role_suggested?: string, tags?: string[]
                      }
                      if (typeof d?.role_suggested === 'string') setEditRole(d.role_suggested)
                      if (Array.isArray(d?.tags)) {
                        const filtered = d.tags.filter(t => t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))
                        setEditTags(filtered.join(' '))
                      }
                    }}>一键匹配（填充）</button>
                  )}
                  <button className={`btn ${BTN_FX}`} onClick={cancelEdit}>取消</button>
                  <button className={`btn btn-primary ${BTN_FX}`} onClick={isCreating ? saveCreate : saveEdit} disabled={saving}>
                    {saving ? '保存中…' : '保存'}
                  </button>
                </>
              )}
            </div>

            {isEditing ? (
              <>
                {/* 识别粘贴框（仅编辑态显示；新增和编辑都可用） */}
                <div className="card p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">识别粘贴框</h4>
                    <button className={`btn ${BTN_FX}`} onClick={() => parseAndPrefillFromText(rawText)}>识别并填充</button>
                  </div>
                  <textarea
                    className="input h-32"
                    placeholder="将网页复制的资料直接粘贴到这里，例如包含：满级配招 / 获得方式 / 种族值 / 技能表 等。"
                    value={rawText}
                    onChange={e => setRawText(e.target.value)}
                  />
                  {createPreferredName && <div className="text-xs text-gray-500">已选择形态：{createPreferredName}</div>}
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
                    <div>
                      <label className="label">定位</label>
                      <select className="select" value={editRole} onChange={e => setEditRole(e.target.value)}>
                        <option value="">未设置</option>
                        <option value="主攻">主攻</option><option value="控制">控制</option>
                        <option value="辅助">辅助</option><option value="坦克">坦克</option><option value="通用">通用</option>
                      </select>
                    </div>

                    {/* 仓库/可获取 */}
                    <div className="flex items-center gap-2">
                      <input id="possess" type="checkbox" checked={editPossess} onChange={e => setEditPossess(e.target.checked)} />
                      <label htmlFor="possess" className="text-sm">已拥有（加入仓库）</label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input id="gettable" type="checkbox" checked={editGettable} onChange={e => setEditGettable(e.target.checked)} />
                      <label htmlFor="gettable" className="text-sm">当前可获取</label>
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
                      <label className="label">标签（空格/逗号分隔，仅支持 buf_*/deb_*/util_*）</label>
                      <input className="input" value={editTags} onChange={e => setEditTags(e.target.value)} />
                      <div className="text-xs text-gray-500 mt-1">
                        将自动忽略旧标签；保存后仅保留新前缀标签。
                      </div>
                    </div>
                  </div>
                </div>

                {/* 基础种族值 */}
                <div className="card p-3 space-y-3">
                  <h4 className="font-semibold">基础种族值（原始六维，直接保存到列）</h4>
                  {[
                    ['体力', hp, setHp],
                    ['速度', speed, setSpeed],
                    ['攻击', attack, setAttack],
                    ['防御', defense, setDefense],
                    ['法术', magic, setMagic],
                    ['抗性', resist, setResist],
                  ].map(([label, val, setter]: any) => (
                    <div key={label} className="grid grid-cols-6 gap-2 items-center">
                      <div className="text-sm text-gray-600 text-center">{label}</div>
                      <input type="range" min={50} max={200} step={1}
                        value={val} onChange={e => (setter as any)(parseInt(e.target.value, 10))} className="col-span-4" />
                      <input className="input py-1 text-center" value={val}
                        onChange={e => (setter as any)(Math.max(0, parseInt(e.target.value || '0', 10)))} />
                    </div>
                  ))}
                  <div className="p-2 bg-gray-50 rounded text-sm text-center">六维总和：<b>{sum}</b></div>
                </div>

                {/* 技能：卡片编辑，右上角紧凑标签 */}
                <div className="card p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">技能</h4>
                    <button className={`btn ${BTN_FX}`} onClick={addSkill}>+ 新增技能</button>
                  </div>
                  <ul className="space-y-3">
                    {editSkills.map((s, idx) => (
                      <li key={idx} className="p-3 bg-gray-50 rounded">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 space-y-2">
                            <div>
                              <label className="label">技能名</label>
                              <input className="input" value={s.name} onChange={e => updateSkill(idx, { name: e.target.value })} />
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                              <div>
                                <label className="label">元素</label>
                                <select className="select" value={s.element || ''} onChange={e => updateSkill(idx, { element: e.target.value })}>
                                  <option value="">未设置</option>
                                  {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
                                </select>
                              </div>
                              <div>
                                <label className="label">种类</label>
                                <input className="input" placeholder="物理/法术/辅助…" value={s.kind || ''} onChange={e => updateSkill(idx, { kind: e.target.value })} />
                              </div>
                              <div>
                                <label className="label">威力</label>
                                <input className="input" type="number" placeholder="如 145" value={(s.power ?? '') as any}
                                       onChange={e => updateSkill(idx, { power: e.target.value === '' ? null : Number(e.target.value) })} />
                              </div>
                            </div>
                            <div>
                              <label className="label">描述</label>
                              <textarea className="input h-24" value={s.description || ''} onChange={e => updateSkill(idx, { description: e.target.value })} />
                            </div>
                          </div>

                          {/* 右上角紧凑标签 + 删除 */}
                          <div className="w-32 text-right shrink-0">
                            <div className="text-[11px] text-gray-500 leading-5">
                              {[s.element || '—', s.kind || '—', (s.power ?? '—')].join(' / ')}
                            </div>
                            <button className={`btn mt-2 ${BTN_FX}`} onClick={() => removeSkill(idx)}>删除</button>
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
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="p-2 bg-gray-50 rounded text-center">体力：<b>{showStats.hp}</b></div>
                    <div className="p-2 bg-gray-50 rounded text-center">速度：<b>{showStats.speed}</b></div>
                    <div className="p-2 bg-gray-50 rounded text-center">攻击：<b>{showStats.attack}</b></div>
                    <div className="p-2 bg-gray-50 rounded text-center">防御：<b>{showStats.defense}</b></div>
                    <div className="p-2 bg-gray-50 rounded text-center">法术：<b>{showStats.magic}</b></div>
                    <div className="p-2 bg-gray-50 rounded text-center">抗性：<b>{showStats.resist}</b></div>
                    <div className="p-2 bg-gray-100 rounded col-span-2 text-center">六维总和：<b>{(showStats as any).sum}</b></div>
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold mb-2">技能</h4>
                  {skills.isLoading && <div className="text-sm text-gray-500">加载中...</div>}
                  {!skills.data?.length && !skills.isLoading && <div className="text-sm text-gray-500">暂无技能数据</div>}
                  <ul className="space-y-2">
                    {skills.data?.filter(s => isValidSkillName(s.name)).map(s => (
                      <li key={`${s.id || s.name}`} className="p-3 bg-gray-50 rounded">
                        <div className="flex items-center justify-between">
                          <div className="font-medium">{s.name}</div>
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

      {/* 全屏模糊等待弹框：支持“确定进度”和“未知进度”两种 */}
      {overlay.show && (
        <div className="fixed inset-0 z-50 backdrop-blur-sm bg-black/20 flex items-center justify-center">
          <div className="rounded-2xl bg-white shadow-xl p-6 w-[min(92vw,420px)] text中心 space-y-3">
            <div className="text-2xl">🐱</div>
            <div className="text-lg font-semibold">{overlay.title || '处理中…'}</div>
            <div className="text-sm text-gray-600">{overlay.sub || '请稍候~'}</div>

            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
              {typeof progressPct === 'number' ? (
                <div className="h-2 bg-purple-300 rounded-full transition-all duration-200" style={{ width: `${progressPct}%` }} />
              ) : (
                <div className="h-2 w-1/2 animate-pulse bg紫色-300 rounded-full" />
              )}
            </div>

            {typeof progressPct === 'number' && (
              <div className="text-xs text-gray-500">
                {overlay.done}/{overlay.total}（成功 {overlay.ok}，失败 {overlay.fail}） — {progressPct}%
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}