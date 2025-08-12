import React, { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import SideDrawer from '../components/SideDrawer'

type RoleCount = { name: string, count: number }
type SkillDTO = { id?: number; name: string; description?: string }
type StatsDTO = { total: number; with_skills: number; tags_total: number }

const isMeaningfulDesc = (t?: string) => {
  if (!t) return false
  const s = t.trim()
  const trivial = new Set(['', '0', '1', '-', '—', '无', '暂无', 'null', 'none', 'N/A', 'n/a'])
  if (trivial.has(s) || trivial.has(s.toLowerCase())) return false
  return s.length >= 6 || /[，。；、,.]/.test(s) ||
    /(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)/.test(s)
}
const isValidSkillName = (name?: string) => !!(name && name.trim() && /[\u4e00-\u9fffA-Za-z]/.test(name))

// —— 统一标签映射（别名→规范）+ 不贪多（最多 6 个）+ 去掉属性词
const TAG_ALIAS: Record<string, string> = {
  '先制': '先手', '先手': '先手',
  '多段': '多段', '三连': '多段', '连击': '多段', '2~3次': '多段', '3~6次': '多段',
  '强化': '强化', '增益': '强化', '提升': '强化',
  '削弱': '削弱', '减益': '削弱', '降低': '削弱', '破防': '破防',
  '免疫': '免疫',
  '高速': '高速', '速度': '高速', '提速': '高速',
  '耐久': '耐久', '回复': '耐久', '治疗': '耐久',
  '控制': '控制', '眩晕': '控制', '昏迷': '控制', '束缚': '控制', '窒息': '控制', '冰冻': '控制',
  '输出': '输出', '暴击': '输出', '高攻': '输出', '无视防御': '输出',
}
function normalizeTags(candidates: string[], limit = 6) {
  const normed: string[] = []
  const seen = new Set<string>()
  for (const raw of candidates) {
    const trimmed = (raw || '').trim()
    if (!trimmed) continue
    if (/^(风|火|水|金|木|土|冰|雷|毒|妖|光|暗|音)系$/.test(trimmed)) continue // 去属性
    let tag = TAG_ALIAS[trimmed] || trimmed
    if (!seen.has(tag)) {
      seen.add(tag); normed.push(tag)
      if (normed.length >= limit) break
    }
  }
  return normed
}

// —— 基于六维 + 技能文本推断 role & tags（启发式）
function inferRoleAndTags(
  stats: { hp:number; speed:number; attack:number; defense:number; magic:number; resist:number },
  skills: SkillDTO[]
) {
  const { hp, speed, attack, defense, magic, resist } = stats
  const tags: string[] = []
  const text = (skills || []).map(s => `${s.name} ${s.description || ''}`).join(' ')
  const has = (re: RegExp) => re.test(text)

  // 数值标签
  if (speed >= 110) tags.push('高速')
  if (attack >= 115) tags.push('输出', '高攻')
  if (hp >= 110 || (defense + magic) / 2 >= 105 || resist >= 110) tags.push('耐久')

  // 技能关键词
  if (has(/(先手|先制)/)) tags.push('先手')
  if (has(/(2~3|3~6|多段|连击)/)) tags.push('多段')
  if (has(/(提高|提升|强化|增益)/)) tags.push('强化')
  if (has(/(降低|削弱|破防|命中下降)/)) tags.push('削弱', '破防')
  if (has(/(昏迷|眩晕|束缚|窒息|冰冻|睡眠)/)) tags.push('控制')
  if (has(/(免疫|免伤)/)) tags.push('免疫')

  const uniq = normalizeTags(tags)

  // role
  let role = '通用'
  const offensive = attack >= 115 || has(/(威力1[3-9]\d|威力[2-9]\d{2}|无视防御|暴击)/)
  const control = has(/(昏迷|眩晕|束缚|窒息|命中下降|速度下降)/) || ((defense + magic) / 2 >= 110)
  const support = has(/(提高|提升|强化|回复|治疗|免疫)/)
  const tanky = hp >= 115 || resist >= 115

  if (offensive && !control && !support) role = '主攻'
  else if (control && !offensive) role = '控制'
  else if (support && !offensive) role = '辅助'
  else if (tanky && !offensive) role = '坦克'
  else role = '通用'

  return { role, tags: uniq }
}

// —— 优先从 explain_json.raw_stats 取（可含小数）；没有就从基础字段近似
function extractIntStats(m: Monster): { hp:number; speed:number; attack:number; defense:number; magic:number; resist:number } {
  const raw = (m as any)?.explain_json?.raw_stats as
    | { hp:number; speed:number; attack:number; defense:number; magic:number; resist:number } | undefined
  if (raw) {
    return {
      hp: Math.round(raw.hp ?? 0),
      speed: Math.round(raw.speed ?? 0),
      attack: Math.round(raw.attack ?? 0),
      defense: Math.round(raw.defense ?? 0),
      magic: Math.round(raw.magic ?? 0),
      resist: Math.round(raw.resist ?? 0),
    }
  }
  const ctrl = Math.round(m.base_control ?? 0)
  return {
    hp: Math.round(m.base_survive ?? 0),
    speed: Math.round(m.base_tempo ?? 0),
    attack: Math.round(m.base_offense ?? 0),
    defense: ctrl,
    magic: ctrl,
    resist: Math.round(m.base_pp ?? 0),
  }
}

export default function MonstersPage() {
  // 搜索 + 筛选
  const [q, setQ] = useState('')
  const [tag, setTag] = useState('')
  const [role, setRole] = useState('')
  const [sort, setSort] = useState<'updated_at' | 'name' | 'offense' | 'survive' | 'control' | 'tempo' | 'pp'>('updated_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')

  // 分页
  const [page, setPage] = useState(1)
  const pageSize = 20

  // 勾选/批量
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // 详情 & 编辑
  const [selected, setSelected] = useState<Monster | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editElement, setEditElement] = useState('')
  const [editRole, setEditRole] = useState('')
  const [editTags, setEditTags] = useState('') // 空格/逗号分隔
  const [hp, setHp] = useState(100)
  const [speed, setSpeed] = useState(100)
  const [attack, setAttack] = useState(100)
  const [defense, setDefense] = useState(100)
  const [magic, setMagic] = useState(100)
  const [resist, setResist] = useState(100)
  const [editSkills, setEditSkills] = useState<SkillDTO[]>([{ name: '', description: '' }])
  const [saving, setSaving] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)

  // 列表 & 基础数据
  const list = useQuery({
    queryKey: ['monsters', { q, tag, role, sort, order, page, pageSize }],
    queryFn: async () =>
      (await api.get('/monsters', {
        params: { q: q || undefined, tag: tag || undefined, role: role || undefined, sort, order, page, page_size: pageSize }
      })).data as MonsterListResp
  })

  // 兼容 /tags 404：失败就返回 []
  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      try {
        return (await api.get('/tags', { params: { with_counts: true } })).data as TagCount[]
      } catch (e: any) {
        if (e?.response?.status === 404) return [] as TagCount[]
        throw e
      }
    }
  })

  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: async () => (await api.get('/roles')).data as RoleCount[]
  })
  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: async () => (await api.get('/stats')).data as StatsDTO
  })
  const skills = useQuery({
    queryKey: ['skills', selected?.id],
    enabled: !!selected?.id,
    queryFn: async () => (await api.get(`/monsters/${selected!.id}/skills`)).data as SkillDTO[]
  })

  // 当 /tags 不可用时，用当前页 items 的 tags 做临时计数
  const localTagCounts: TagCount[] = useMemo(() => {
    if (tags.data && tags.data.length > 0) return tags.data
    const map = new Map<string, number>()
    for (const m of (list.data?.items || [])) {
      for (const t of (m.tags || [])) map.set(t, (map.get(t) || 0) + 1)
    }
    return Array.from(map.entries()).map(([name, count]) => ({ name, count }))
  }, [tags.data, list.data])

  // 展示用六维：优先 raw（可含小数），确保“原版导入”完整显示
  const raw = (selected as any)?.explain_json?.raw_stats as
    | { hp: number, speed: number, attack: number, defense: number, magic: number, resist: number, sum?: number }
    | undefined
  const showStats = raw ? {
    hp: raw.hp, speed: raw.speed, attack: raw.attack,
    defense: raw.defense, magic: raw.magic, resist: raw.resist,
    sum: (raw.hp||0)+(raw.speed||0)+(raw.attack||0)+(raw.defense||0)+(raw.magic||0)+(raw.resist||0),
  } : {
    hp: selected?.base_survive ?? 0,
    speed: selected?.base_tempo ?? 0,
    attack: selected?.base_offense ?? 0,
    defense: selected?.base_control ?? 0,
    magic: selected?.base_control ?? 0,
    resist: selected?.base_pp ?? 0,
    sum:
      (selected?.base_survive ?? 0) +
      (selected?.base_tempo ?? 0) +
      (selected?.base_offense ?? 0) +
      (selected?.base_control ?? 0) +
      (selected?.base_control ?? 0) +
      (selected?.base_pp ?? 0),
  }
  const sum = useMemo(() => hp + speed + attack + defense + magic + resist, [hp, speed, attack, defense, magic, resist])

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
    const ids = list.data?.items?.map(i => i.id) || []
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
    if (selected?.id === id) setSelected(null)
    list.refetch(); stats.refetch()
  }

  // —— 导出/备份/恢复
  const restoreInputRef = useRef<HTMLInputElement>(null)
  const exportCSV = async () => {
    const res = await api.get('/export/monsters.csv', {
      params: { q: q || undefined, tag: tag || undefined, role: role || undefined, sort, order },
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
  const openDetail = (m: Monster) => {
    setSelected(m)
    setIsEditing(false)
  }

  // —— 进入编辑：预填原值（编辑用整数，展示仍用原版 raw）
  const enterEdit = () => {
    if (!selected) return
    setEditName(selected.name_final || '')
    setEditElement(selected.element || '')
    setEditRole(selected.role || '')
    setEditTags((selected.tags || []).join(' '))
    const r = (selected as any)?.explain_json?.raw_stats
    if (r) {
      setHp(Math.round(r.hp ?? 100)); setSpeed(Math.round(r.speed ?? 100)); setAttack(Math.round(r.attack ?? 100))
      setDefense(Math.round(r.defense ?? 100)); setMagic(Math.round(r.magic ?? 100)); setResist(Math.round(r.resist ?? 100))
    } else {
      setHp(Math.round(selected.base_survive ?? 100)); setSpeed(Math.round(selected.base_tempo ?? 100)); setAttack(Math.round(selected.base_offense ?? 100))
      setDefense(Math.round(selected.base_control ?? 100)); setMagic(Math.round(selected.base_control ?? 100)); setResist(Math.round(selected.base_pp ?? 100))
    }
    const existing = (skills.data || []).map(s => ({ name: s.name || '', description: s.description || '' }))
    setEditSkills(existing.length ? existing : [{ name: '', description: '' }])
    setIsEditing(true)
  }
  const cancelEdit = () => setIsEditing(false)

  // —— 保存：技能带方法降级（PUT→POST→/skills/set）
  const saveSkillsWithFallback = async (monsterId: number, skillsBody: SkillDTO[]) => {
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

  // —— 保存（基础 + 技能）👉 base_control 四舍五入，避免 422
  const saveEdit = async () => {
    if (!selected) return
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      const base_offense = Math.round(attack)
      const base_survive = Math.round(hp)
      const base_control = Math.round((Number(defense) + Number(magic)) / 2) // 关键：取整
      const base_tempo = Math.round(speed)
      const base_pp = Math.round(resist)

      const payload = {
        name_final: editName.trim(),
        element: editElement || null,
        role: editRole || null,
        base_offense, base_survive, base_control, base_tempo, base_pp,
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(Boolean),
      }
      await api.put(`/monsters/${selected.id}`, payload)

      const filtered = editSkills.filter(s => (s.name || '').trim())
      await saveSkillsWithFallback(selected.id, filtered)

      const fresh = (await api.get(`/monsters/${selected.id}`)).data as Monster
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

  // —— 主页一键自动匹配（选中优先，否则对当前页可见项）
  const autoMatchBatch = async () => {
    const items = list.data?.items || []
    if (!items.length) return alert('当前没有可处理的记录')
    const target = selectedIds.size ? items.filter(i => selectedIds.has(i.id)) : items
    if (!target.length) return alert('请勾选一些记录，或直接对当前页可见项执行。')
    if (!window.confirm(`将对 ${target.length} 条记录执行“自动匹配”：定位、攻/生/控/速/PP、标签。是否继续？`)) return

    setAutoMatching(true)
    let ok = 0, fail = 0
    for (const m of target) {
      try {
        const fresh = (await api.get(`/monsters/${m.id}`)).data as Monster
        const sks = (await api.get(`/monsters/${m.id}/skills`)).data as SkillDTO[]
        const s = extractIntStats(fresh)
        const base_offense = s.attack
        const base_survive = s.hp
        const base_control = Math.round((s.defense + s.magic) / 2) // 取整，避免 422
        const base_tempo = s.speed
        const base_pp = s.resist
        const { role: inferRole, tags: inferTags } = inferRoleAndTags(s, sks)

        await api.put(`/monsters/${m.id}`, {
          name_final: fresh.name_final,
          element: fresh.element || null,
          role: inferRole,
          base_offense, base_survive, base_control, base_tempo, base_pp,
          tags: inferTags,
        })
        ok++
      } catch {
        fail++
      }
    }
    setAutoMatching(false)
    list.refetch(); stats.refetch()
    alert(`自动匹配完成：成功 ${ok} 条，失败 ${fail} 条。`)
  }

  // —— 抽屉内一键匹配：把推断结果直接填入当前编辑表单（可再次微调后保存）
  const fillEditByAutoMatch = () => {
    if (!selected) return
    const s = extractIntStats(selected)
    setHp(s.hp); setSpeed(s.speed); setAttack(s.attack); setDefense(s.defense); setMagic(s.magic); setResist(s.resist)
    const { role: inferRole, tags: inferTags } = inferRoleAndTags(s, skills.data || [])
    setEditRole(inferRole)
    setEditTags(inferTags.join(' '))
    if (!isEditing) setIsEditing(true)
  }

  return (
    <div className="container my-6 space-y-4">
      {/* 工具栏 */}
      <div className="card p-4">
        <div className="mb-3">
          <input
            className="input"
            placeholder="搜索名称 / 技能关键词…"
            value={q}
            onChange={e => { setQ(e.target.value); setPage(1) }}
            aria-label="搜索"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <select className="select" value={tag} onChange={e => { setTag(e.target.value); setPage(1) }}>
            <option value="">标签</option>
            {(localTagCounts || []).map(t => <option key={t.name} value={t.name}>{t.name}（{t.count}）</option>)}
          </select>
          <select className="select" value={role} onChange={e => { setRole(e.target.value); setPage(1) }}>
            <option value="">定位</option>
            {roles.data?.map(r => <option key={r.name} value={r.name}>{r.count ? `${r.name}（${r.count}）` : r.name}</option>)}
          </select>
          <select className="select" value={sort} onChange={e => setSort(e.target.value as any)}>
            <option value="updated_at">更新时间</option>
          </select>
          <select className="select" value={order} onChange={e => setOrder(e.target.value as any)}>
            <option value="desc">降序</option>
            <option value="asc">升序</option>
          </select>
        </div>
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button className="btn" onClick={() => list.refetch()}>刷新</button>
          <button className="btn" onClick={exportCSV}>导出 CSV</button>
          <button className="btn" onClick={exportBackup}>备份 JSON</button>
          <button className="btn" onClick={openRestore}>恢复 JSON</button>
          <input id="restoreInput" ref={restoreInputRef} type="file" accept="application/json" className="hidden" onChange={onRestoreFile} />
          <button className="btn btn-primary" onClick={autoMatchBatch} disabled={autoMatching}>
            {autoMatching ? '自动匹配中…' : '自动匹配（选中/可见）'}
          </button>
        </div>
      </div>

      {/* 统计栏 */}
      <div className="card p-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs text-gray-500">总数</div>
            <div className="text-xl font-semibold">{stats.data?.total ?? '—'}</div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
            <div className="text-xs text-gray-500">有技能</div>
            <div className="text-xl font-semibold">{stats.data?.with_skills ?? '—'}</div>
          </div>
          <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
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

      {/* 列表 */}
      <div className="card">
        <div className="overflow-auto">
          <table className="table">
            <thead>
              <tr>
                <th className="w-10">
                  <input
                    type="checkbox"
                    aria-label="全选"
                    checked={!!list.data?.items?.length && list.data.items.every(i => selectedIds.has(i.id))}
                    onChange={toggleAllVisible}
                  />
                </th>
                <th className="w-14">ID</th>
                <th>名称</th>
                <th>元素</th>
                <th>定位</th>
                <th>攻</th>
                <th>生</th>
                <th>控</th>
                <th>速</th>
                <th>PP</th>
                <th>标签</th>
              </tr>
            </thead>
            {list.isLoading && <SkeletonRows rows={8} cols={11} />}
            {!list.isLoading && (
              <tbody>
                {list.data?.items?.map((m: Monster) => (
                  <tr key={m.id}>
                    <td>
                      <input type="checkbox" checked={selectedIds.has(m.id)} onChange={() => toggleOne(m.id)} />
                    </td>
                    <td>{m.id}</td>
                    <td>
                      <button className="text-blue-600 hover:underline" onClick={() => openDetail(m)}>
                        {m.name_final}
                      </button>
                    </td>
                    <td>{m.element}</td>
                    <td>{m.role}</td>
                    <td>{m.base_offense}</td>
                    <td>{m.base_survive}</td>
                    <td>{m.base_control}</td>
                    <td>{m.base_tempo}</td>
                    <td>{m.base_pp}</td>
                    <td className="space-x-1">
                      {m.tags?.map(t => <span key={t} className="badge">{t}</span>)}
                    </td>
                  </tr>
                ))}
                {list.data?.items?.length === 0 && (
                  <tr>
                    <td colSpan={11} className="text-center text-gray-500 py-6">没有数据。请调整筛选或导入 CSV。</td>
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

      {/* 详情抽屉（内置编辑） */}
      <SideDrawer open={!!selected} onClose={() => { setSelected(null); setIsEditing(false) }} title={selected?.name_final}>
        {selected && (
          <div className="space-y-5">
            <div className="flex items-center justify-end gap-2">
              {!isEditing ? (
                <>
                  <button className="btn" onClick={enterEdit}>编辑</button>
                  <button className="btn" onClick={() => deleteOne(selected.id)}>删除</button>
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
                <div>
                  <h4 className="font-semibold mb-2">基础种族值（六维）</h4>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="p-2 bg-gray-50 rounded">体力：<b>{showStats.hp}</b></div>
                    <div className="p-2 bg-gray-50 rounded">速度：<b>{showStats.speed}</b></div>
                    <div className="p-2 bg-gray-50 rounded">攻击：<b>{showStats.attack}</b></div>
                    <div className="p-2 bg-gray-50 rounded">防御：<b>{showStats.defense}</b></div>
                    <div className="p-2 bg-gray-50 rounded">法术：<b>{showStats.magic}</b></div>
                    <div className="p-2 bg-gray-50 rounded">抗性：<b>{showStats.resist}</b></div>
                    <div className="p-2 bg-gray-100 rounded col-span-2 text-center">六维总和：<b>{(showStats as any).sum}</b></div>
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold mb-2">技能</h4>
                  {skills.isLoading && <div className="text-sm text-gray-500">加载中...</div>}
                  {!skills.data?.length && !skills.isLoading && <div className="text-sm text-gray-500">暂无技能数据</div>}
                  <ul className="space-y-2">
                    {skills.data?.filter(s => isValidSkillName(s.name)).map(s => (
                      <li key={s.id} className="p-2 bg-gray-50 rounded">
                        <div className="font-medium">{s.name}</div>
                        {isMeaningfulDesc(s.description) && (
                          <div className="text-sm text-gray-600 whitespace-pre-wrap">{s.description}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>

                {(selected as any)?.explain_json?.summary && (
                  <div>
                    <h4 className="font-semibold mb-2">评价 / 总结（主观）</h4>
                    <div className="p-3 bg-gray-50 rounded text-sm whitespace-pre-wrap">
                      {(selected as any).explain_json.summary}
                    </div>
                  </div>
                )}

                <div>
                  <h4 className="font-semibold mb-2">标签</h4>
                  <div className="space-x-1">
                    {selected.tags?.map(t => <span key={t} className="badge">{t}</span>)}
                  </div>
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
                        <option value="金">金</option><option value="木">木</option>
                        <option value="水">水</option><option value="火">火</option><option value="土">土</option>
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
                    <div className="md:col-span-2">
                      <label className="label">标签（空格/逗号分隔）</label>
                      <input className="input" value={editTags} onChange={e => setEditTags(e.target.value)} />
                    </div>
                  </div>
                </div>

                <div className="card p-3 space-y-3">
                  <h4 className="font-semibold">基础种族值（六维）</h4>
                  {[
                    ['体力', hp, setHp],
                    ['速度', speed, setSpeed],
                    ['攻击', attack, setAttack],
                    ['防御', defense, setDefense],
                    ['法术', magic, setMagic],
                    ['抗性', resist, setResist],
                  ].map(([label, val, setter]: any) => (
                    <div key={label} className="grid grid-cols-6 gap-2 items-center">
                      <div className="text-sm text-gray-600">{label}</div>
                      <input type="range" min={50} max={200} step={1}
                        value={val} onChange={e => (setter as any)(parseInt(e.target.value, 10))} className="col-span-4" />
                      <input className="input py-1" value={val}
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