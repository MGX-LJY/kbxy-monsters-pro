// client/src/pages/MonstersPage.tsx
import React, { useMemo, useRef, useState } from 'react'
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

type StatsDTO = { total: number; with_skills: number; tags_total: number }

type SortKey = 'updated_at' | 'offense' | 'survive' | 'control' | 'tempo' | 'pp_pressure'

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

// —— 统一 code -> 中文（补齐所有后端 code，避免英文直出） —— //
const TAG_LABELS: Record<string, string> = {
  // 增强类（buff）
  'buf_atk_up': '攻↑',
  'buf_mag_up': '法↑',
  'buf_spd_up': '速↑',
  'buf_def_up': '防↑',
  'buf_res_up': '抗↑',
  'buf_acc_up': '命中↑',
  'buf_crit_up': '暴击↑',
  'buf_heal': '治疗',
  'buf_shield': '护盾/减伤',
  'buf_purify': '净化己减益',
  'buf_immunity': '免疫异常',

  // 削弱类（debuff）
  'deb_atk_down': '攻↓',
  'deb_mag_down': '法术↓',
  'deb_def_down': '防↓',
  'deb_res_down': '抗↓',
  'deb_spd_down': '速↓',
  'deb_acc_down': '命中↓',
  'deb_stun': '眩晕/昏迷',
  'deb_bind': '束缚/禁锢',
  'deb_sleep': '睡眠',
  'deb_freeze': '冰冻',
  'deb_confuse_seal': '混乱/封印',
  'deb_suffocate': '窒息',
  'deb_dot': '持续伤害',
  'deb_dispel': '驱散敌增益',

  // 特殊类（utility）
  'util_first': '先手',
  'util_multi': '多段',
  'util_pp_drain': 'PP压制',
  'util_reflect': '反击/反伤',
  'util_charge_next': '加倍/下一击强',
  'util_penetrate': '穿透/破盾',
}
const tagLabel = (code: string) => TAG_LABELS[code] || code

export default function MonstersPage() {
  // 搜索 + 筛选
  const [q, setQ] = useState('')
  const [element, setElement] = useState('')           // 元素筛选
  const [tag, setTag] = useState('')                   // 单一 tag 后端筛选（保留）
  const [role, setRole] = useState('')
  const [sort, setSort] = useState<SortKey>('updated_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')

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
  const [editPossess, setEditPossess] = useState<boolean>(false)      // 新增：仓库/已拥有
  const [editGettable, setEditGettable] = useState<boolean>(false)    // 新增：当前可获取

  // —— 六维：直接读/写数据库列 —— //
  const [hp, setHp] = useState<number>(100)
  const [speed, setSpeed] = useState<number>(100)
  const [attack, setAttack] = useState<number>(100)
  const [defense, setDefense] = useState<number>(100)
  const [magic, setMagic] = useState<number>(100)
  const [resist, setResist] = useState<number>(100)

  // 编辑态的技能（仅 name/description，显示时会带 element/kind/power）
  const [editSkills, setEditSkills] = useState<{ name: string; description?: string }[]>([{ name: '', description: '' }])
  const [saving, setSaving] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)

  // —— 一键爬取（按钮已移动到“自动匹配”旁） —— //
  const [crawling, setCrawling] = useState(false)
  const [crawlLimit, setCrawlLimit] = useState<string>('') // 上限输入框已移到搜索框旁

  const startCrawl = async () => {
    if (!window.confirm(`将触发后端“全站爬取图鉴”。${crawlLimit ? `最多抓取 ${crawlLimit} 条。` : '将尽可能多地抓取。'}是否继续？`)) return
    setCrawling(true)
    try {
      const payload: any = {}
      if (crawlLimit && /^\d+$/.test(crawlLimit)) payload.limit = parseInt(crawlLimit, 10)
      const res = await api.post('/api/v1/crawl/4399/crawl_all', payload)
      const d = res?.data || {}
      // 适配新返回（seen/inserted/updated/skills_changed）
      alert(`完成：遍历 ${d.seen||0}，新增 ${d.inserted||0}，更新 ${d.updated||0}，技能变更 ${d.skills_changed||0}`)
      await Promise.all([list.refetch(), stats.refetch()])
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

  // 列表 & 基础数据
  const list = useQuery({
    queryKey: ['monsters', { q, element, tag, role, sort, order, page, pageSize }],
    queryFn: async () =>
      (await api.get('/monsters', {
        params: {
          q: q || undefined,
          element: element || undefined,
          tag: tag || undefined,         // 后端仍是单一 tag 入参
          role: role || undefined,
          sort,
          order,
          page,
          page_size: pageSize
        }
      })).data as MonsterListResp
  })

  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      try {
        const d = (await api.get('/tags', { params: { with_counts: true } })).data
        const arr: TagCount[] = Array.isArray(d) ? d : (d?.items || [])
        // 仅保留新前缀标签
        return (arr || []).filter(t =>
          t?.name?.startsWith('buf_') || t?.name?.startsWith('deb_') || t?.name?.startsWith('util_')
        )
      } catch {
        return [] as TagCount[]
      }
    }
  })

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

  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get('/stats')).data as StatsDTO
  })

  const skills = useQuery({
    queryKey: ['skills', (selected as any)?.id],
    enabled: !!(selected as any)?.id,
    queryFn: async () => (await api.get(`/monsters/${(selected as any)!.id}/skills`)).data as SkillDTO[]
  })

  // 当 /tags 不可用时，用当前页 items 的 tags 做临时计数（同样只保留新前缀）
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

  // —— 展示用六维（直接来自 selected 的列） —— //
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

  // —— 批量选择
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

  // —— 删除
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
  }
  const deleteOne = async (id: number) => {
    if (!window.confirm('确认删除该宠物？此操作不可撤销。')) return
    await api.delete(`/monsters/${id}`)
    if ((selected as any)?.id === id) setSelected(null)
    list.refetch(); stats.refetch()
  }

  // —— 导出/备份/恢复
  const restoreInputRef = useRef<HTMLInputElement>(null)
  const exportCSV = async () => {
    const res = await api.get('/export/monsters.csv', {
      params: { q: q || undefined, element: element || undefined, tag: tag || undefined, role: role || undefined, sort, order },
      responseType: 'blob'
    })
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
      list.refetch(); stats.refetch()
    } catch (err: any) {
      alert('恢复失败：' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      e.target.value = ''
    }
  }

  // —— 打开详情
  const openDetail = (m: Monster | any) => {
    setSelected(m)
    setIsEditing(false)
  }

  // —— 进入编辑：预填
  const enterEdit = () => {
    if (!selected) return
    const s: any = selected
    setEditName(s.name || s.name_final || '')
    setEditElement(s.element || '')
    setEditRole(s.role || '')
    setEditPossess(!!s.possess)
    setEditGettable(!!s.new_type)

    // 只把新前缀标签写入编辑框
    const onlyNew = (s.tags || []).filter((t: string) => t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))
    setEditTags(onlyNew.join(' '))

    setHp(Math.round(s.hp ?? 100))
    setSpeed(Math.round(s.speed ?? 100))
    setAttack(Math.round(s.attack ?? 100))
    setDefense(Math.round(s.defense ?? 100))
    setMagic(Math.round(s.magic ?? 100))
    setResist(Math.round(s.resist ?? 100))

    const existing = (skills.data || []).map(s => ({ name: s.name || '', description: s.description || '' }))
    setEditSkills(existing.length ? existing : [{ name: '', description: '' }])
    setIsEditing(true)
  }
  const cancelEdit = () => setIsEditing(false)

  // —— 保存技能（保持后兼容，body 里只带 name/description；后端用唯一键做 upsert） —— //
  const saveSkillsWithFallback = async (monsterId: number, skillsBody: { name: string; description?: string }[]) => {
    try {
      return await api.put(`/monsters/${monsterId}/skills`, { skills: skillsBody })
    } catch (e: any) {
      const st = e?.response?.status
      if (st === 405 || st === 404) {
        try {
          return await api.post(`/monsters/${monsterId}/skills`, { skills: skillsBody })
        } catch {
          return await api.post(`/skills/set`, { monster_id: monsterId, skills: skillsBody })
        }
      }
      throw e
    }
  }

  // —— 保存（一次性 PUT /monsters/{id}） —— //
  const saveEdit = async () => {
    if (!selected) return
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      await api.put(`/monsters/${(selected as any).id}`, {
        // 适配新后端：name 字段
        name: editName.trim(),
        element: editElement || null,
        role: editRole || null,
        possess: !!editPossess,           // 新增
        new_type: !!editGettable,        // 新增
        hp, speed, attack, defense, magic, resist,
        // 仅保存新前缀标签到 Monster.tags
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(t => t && (t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))),
      })

      // 技能
      const filtered = editSkills.filter(s => (s.name || '').trim())
      await saveSkillsWithFallback((selected as any).id, filtered)

      // 刷新
      const fresh = (await api.get(`/monsters/${(selected as any).id}`)).data as Monster
      setSelected(fresh)
      skills.refetch()
      list.refetch()
      setIsEditing(false)
    } catch (e: any) {
      alert(e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // —— 主页一键自动匹配：优先 /monsters/auto_match，失败逐条兜底
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

  // —— 抽屉内“一键匹配（填充）”：拉取建议写入编辑框
  const fillEditByAutoMatch = async () => {
    if (!selected) return
    const d = (await api.get(`/monsters/${(selected as any).id}/derived`)).data as {
      role_suggested?: string, tags?: string[]
    }
    if (typeof d?.role_suggested === 'string') setEditRole(d.role_suggested)
    if (Array.isArray(d?.tags)) {
      const filtered = d.tags.filter(t => t.startsWith('buf_') || t.startsWith('deb_') || t.startsWith('util_'))
      setEditTags(filtered.join(' '))
    }
    if (!isEditing) setIsEditing(true)
  }

  // 元素选项（可按项目实际补充）
  const elementOptions = ['金','木','水','火','土','风','雷','冰','毒','妖','光','暗','音']

  return (
    <div className="container my-6 space-y-4">
      {/* 工具栏 */}
      <div className="card p-4">
        {/* 第一行：搜索 + 爬取上限(移到搜索旁) + 刷新/导出/备份/恢复 */}
        <div className="mb-3 grid grid-cols-1 md:grid-cols-3 gap-3 items-center">
          <div className="flex items-center gap-2">
            <input
              className="input flex-1"
              placeholder="搜索名称 / 技能关键词…"
              value={q}
              onChange={e => { setQ(e.target.value); setPage(1) }}
              aria-label="搜索"
            />
            {/* 爬取上限放在搜索框旁边 */}
            <input
              className="input w-32"
              placeholder="抓取上限(可选)"
              value={crawlLimit}
              onChange={e => setCrawlLimit(e.target.value.replace(/[^\d]/g, ''))}
            />
          </div>
          <div className="hidden md:block" />
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={() => list.refetch()}>刷新</button>
            <button className="btn" onClick={exportCSV}>导出 CSV</button>
            <button className="btn" onClick={exportBackup}>备份 JSON</button>
            <button className="btn" onClick={openRestore}>恢复 JSON</button>
            <input id="restoreInput" ref={restoreInputRef} type="file" accept="application/json" className="hidden" onChange={onRestoreFile} />
          </div>
        </div>

        {/* 第二行：元素 + 标签(汉化显示) + 定位 + 排序 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <select className="select" value={element} onChange={e => { setElement(e.target.value); setPage(1) }}>
            <option value="">元素</option>
            {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
          </select>
          <select className="select" value={tag} onChange={e => { setTag(e.target.value); setPage(1) }}>
            <option value="">标签（全部）</option>
            {(localTagCounts || []).map(t =>
              <option key={t.name} value={t.name}>{tagLabel(t.name)}（{t.count}）</option>
            )}
          </select>
          <select className="select" value={role} onChange={e => { setRole(e.target.value); setPage(1) }}>
            <option value="">定位</option>
            {roles.data?.map(r => <option key={r.name} value={r.name}>{r.count ? `${r.name}（${r.count}）` : r.name}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3">
            <select className="select" value={sort} onChange={e => setSort(e.target.value as SortKey)}>
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

        {/* 第三行：操作按钮区 —— 把“一键爬取”挪到“自动匹配”旁边 */}
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button className="btn" onClick={startCrawl} disabled={crawling}>
            {crawling ? '爬取中…' : '一键爬取图鉴'}
          </button>
          <button className="btn btn-primary" onClick={autoMatchBatch} disabled={autoMatching}>
            {autoMatching ? '自动匹配中…' : '自动匹配（选中/可见）'}
          </button>
        </div>
      </div>

      {/* 统计栏 */}
      <div className="card p-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">总数</div>
            <div className="text-xl font-semibold">{stats.data?.total ?? '—'}</div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">有技能</div>
            <div className="text-xl font-semibold">{stats.data?.with_skills ?? '—'}</div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-center">
            <div className="text-xs text-gray-500">标签总数</div>
            <div className="text-xl font-semibold">{stats.data?.tags_total ?? '—'}</div>
          </div>
        </div>
      </div>

      {/* 批量操作条 */}
      {selectedIds.size > 0 && (
        <div className="card p-3 flex items-center justify-between">
          <div className="text-sm text-gray-600">已选 {selectedIds.size} 项</div>
          <div className="flex items-center gap-2">
            <button className="btn" onClick={() => setSelectedIds(new Set())}>清除选择</button>
            <button className="btn btn-primary" onClick={bulkDelete}>批量删除</button>
          </div>
        </div>
      )}

      {/* 列表（展示派生五维 + 三列标签） */}
      <div className="card">
        <div className="overflow-auto">
          <table className="table">
            <thead>
              <tr>
                <th className="w-8 text-center">
                  <input
                    type="checkbox"
                    aria-label="全选"
                    checked={!!(list.data?.items as any[])?.length && (list.data!.items as any[]).every((i: any) => selectedIds.has(i.id))}
                    onChange={toggleAllVisible}
                  />
                </th>
                <th className="w-14 text-center">ID</th>
                <th className="text-left">名称</th>
                <th className="text-center">元素</th>
                <th className="text-center">定位</th>
                <th className="text-center">攻</th>
                <th className="text-center">生</th>
                <th className="text-center">控</th>
                <th className="text-center">速</th>
                <th className="text-center">压</th>
                <th className="text-center">增强</th>
                <th className="text-center">削弱</th>
                <th className="text-center">特殊</th>
              </tr>
            </thead>
            {list.isLoading && <SkeletonRows rows={8} cols={13} />}
            {!list.isLoading && (
              <tbody>
                {(list.data?.items as any[])?.map((m: any) => {
                  const buckets = bucketizeTags(m.tags)
                  const chips = (arr: string[], prefixEmoji: string) =>
                    arr.slice(0, 4).map(t => <span key={t} className="badge">{prefixEmoji}{tagLabel(t)}</span>)
                  return (
                    <tr key={m.id}>
                      <td className="text-center">
                        <input type="checkbox" checked={selectedIds.has(m.id)} onChange={() => toggleOne(m.id)} />
                      </td>
                      <td className="text-center">{m.id}</td>
                      <td className="text-left">
                        <button className="text-blue-600 hover:underline" onClick={() => openDetail(m)}>
                          {m.name || m.name_final /* 兜底兼容 */}
                        </button>
                      </td>
                      <td className="text-center">{m.element}</td>
                      <td className="text-center">{m.role || (m as any).derived?.role_suggested || ''}</td>
                      <td className="text-center">{m.derived?.offense ?? 0}</td>
                      <td className="text-center">{m.derived?.survive ?? 0}</td>
                      <td className="text-center">{m.derived?.control ?? 0}</td>
                      <td className="text-center">{m.derived?.tempo ?? 0}</td>
                      <td className="text-center">{(m.derived as any)?.pp_pressure ?? 0}</td>
                      <td className="text-center">
                        <div className="inline-flex flex-wrap gap-1 justify-center">
                          {chips(buckets.buf, '🟢')}
                        </div>
                      </td>
                      <td className="text-center">
                        <div className="inline-flex flex-wrap gap-1 justify-center">
                          {chips(buckets.deb, '🔴')}
                        </div>
                      </td>
                      <td className="text-center">
                        <div className="inline-flex flex-wrap gap-1 justify-center">
                          {chips(buckets.util, '🟣')}
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {(list.data?.items as any[])?.length === 0 && (
                  <tr>
                    <td colSpan={13} className="text-center text-gray-500 py-6">没有数据。请调整筛选或导入 JSON/CSV。</td>
                  </tr>
                )}
              </tbody>
            )}
          </table>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <div className="text-sm text-gray-500">ETag: {list.data?.etag}</div>
          <Pagination page={page} pageSize={pageSize} total={list.data?.total || 0} onPageChange={setPage} />
        </div>
      </div>

      {/* 详情抽屉：六维直接显示列；编辑时直接保存到列；名称/拥有/可获取等新字段 */}
      <SideDrawer open={!!selected} onClose={() => { setSelected(null); setIsEditing(false) }} title={(selected as any)?.name || (selected as any)?.name_final}>
        {selected && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center justify-end gap-2">
              {!isEditing ? (
                <>
                  <span className="text-sm text-gray-600 mr-auto">
                    {/* 新增：当前可获取徽标 */}
                    {(selected as any)?.new_type === true && <span className="badge badge-success mr-2">可获取</span>}
                    {(selected as any)?.new_type === false && <span className="badge badge-warning mr-2">暂不可</span>}
                    {(selected as any)?.possess && <span className="badge badge-info">已拥有</span>}
                  </span>
                  <button className="btn" onClick={async () => {
                    try { await api.get(`/monsters/${(selected as any).id}/derived`) } catch {}
                    enterEdit()
                  }}>编辑</button>
                  <button className="btn" onClick={() => deleteOne((selected as any).id)}>删除</button>
                </>
              ) : (
                <>
                  <button className="btn" onClick={fillEditByAutoMatch}>一键匹配（填充）</button>
                  <button className="btn" onClick={cancelEdit}>取消</button>
                  <button className="btn btn-primary" onClick={saveEdit} disabled={saving}>{saving ? '保存中…' : '保存'}</button>
                </>
              )}
            </div>

            {!isEditing ? (
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
                          {/* 新增：显示 element/kind/power */}
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

                {/* 标签分三类展示（不再显示“其它”） */}
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
            ) : (
              <>
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
                    {/* 新增：拥有/可获取 开关 */}
                    <div className="flex items-center gap-2">
                      <input id="possess" type="checkbox" checked={editPossess} onChange={e => setEditPossess(e.target.checked)} />
                      <label htmlFor="possess" className="text-sm">已拥有（加入仓库）</label>
                    </div>
                    <div className="flex items-center gap-2">
                      <input id="gettable" type="checkbox" checked={editGettable} onChange={e => setEditGettable(e.target.checked)} />
                      <label htmlFor="gettable" className="text-sm">当前可获取</label>
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

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-semibold">技能（可编辑/添加多个）</h4>
                    <button className="btn" onClick={() => setEditSkills(prev => [...prev, { name: '', description: '' }])}>
                      + 添加技能
                    </button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {editSkills.map((s, idx) => (
                      <div key={idx} className="card p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <input className="input flex-1" value={s.name}
                            placeholder={`技能 ${idx + 1} 名称`}
                            onChange={e => setEditSkills(prev => prev.map((x, i) => i === idx ? { ...x, name: e.target.value } : x))} />
                          <button className="btn" onClick={() => setEditSkills(prev => prev.filter((_, i) => i !== idx))} disabled={editSkills.length === 1}>删除</button>
                        </div>
                        <textarea className="input h-24" value={s.description || ''} placeholder="技能描述"
                          onChange={e => setEditSkills(prev => prev.map((x, i) => i === idx ? { ...x, description: e.target.value } : x))} />
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </SideDrawer>
    </div>
  )
}