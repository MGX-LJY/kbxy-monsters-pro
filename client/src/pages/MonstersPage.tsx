// client/src/pages/MonstersPage.tsx
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

export default function MonstersPage() {
  // 搜索 + 筛选
  const [q, setQ] = useState('')
  const [element, setElement] = useState('')           // 元素筛选
  const [tag, setTag] = useState('')
  const [role, setRole] = useState('')
  const [sort, setSort] = useState<SortKey>('updated_at')  // 支持派生字段排序
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
  const [editTags, setEditTags] = useState('')
  const [hp, setHp] = useState<number>(100)
  const [speed, setSpeed] = useState<number>(100)
  const [attack, setAttack] = useState<number>(100)
  const [defense, setDefense] = useState<number>(100)
  const [magic, setMagic] = useState<number>(100)
  const [resist, setResist] = useState<number>(100)
  const [editSkills, setEditSkills] = useState<SkillDTO[]>([{ name: '', description: '' }])
  const [saving, setSaving] = useState(false)
  const [autoMatching, setAutoMatching] = useState(false)

  // 列表 & 基础数据
  const list = useQuery({
    queryKey: ['monsters', { q, element, tag, role, sort, order, page, pageSize }],
    queryFn: async () =>
      (await api.get('/monsters', {
        params: {
          q: q || undefined,
          element: element || undefined,
          tag: tag || undefined,
          role: role || undefined,
          sort,
          order,
          page,
          page_size: pageSize
        }
      })).data as MonsterListResp
  })

  // 兼容 /tags 返回结构差异
  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      try {
        const d = (await api.get('/tags', { params: { with_counts: true } })).data
        return Array.isArray(d) ? d as TagCount[] : (d?.items || []) as TagCount[]
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

  // —— 展示用原始六维（直接读数据库字段，不再用 raw_stats 兜底）
  const showStats = selected ? {
    hp: Math.round(selected.hp || 0),
    speed: Math.round(selected.speed || 0),
    attack: Math.round(selected.attack || 0),
    defense: Math.round(selected.defense || 0),
    magic: Math.round(selected.magic || 0),
    resist: Math.round(selected.resist || 0),
    sum: Math.round((selected.hp || 0) + (selected.speed || 0) + (selected.attack || 0) + (selected.defense || 0) + (selected.magic || 0) + (selected.resist || 0)),
  } : {
    hp: 0, speed: 0, attack: 0, defense: 0, magic: 0, resist: 0, sum: 0
  }

  const sum = useMemo(() =>
    hp + speed + attack + defense + magic + resist,
    [hp, speed, attack, defense, magic, resist]
  )

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
  const openDetail = (m: Monster) => {
    setSelected(m)
    setIsEditing(false)
  }

  // —— 进入编辑：表单初值直接用数据库字段（不再从 raw_stats 取）
  const enterEdit = () => {
    if (!selected) return
    setEditName(selected.name_final || '')
    setEditElement(selected.element || '')
    setEditRole(selected.role || '')
    setEditTags((selected.tags || []).join(' '))

    setHp(Math.round(selected.hp ?? 100))
    setSpeed(Math.round(selected.speed ?? 100))
    setAttack(Math.round(selected.attack ?? 100))
    setDefense(Math.round(selected.defense ?? 100))
    setMagic(Math.round(selected.magic ?? 100))
    setResist(Math.round(selected.resist ?? 100))

    const existing = (skills.data || []).map(s => ({ name: s.name || '', description: s.description || '' }))
    setEditSkills(existing.length ? existing : [{ name: '', description: '' }])
    setIsEditing(true)
  }
  const cancelEdit = () => setIsEditing(false)

  // —— 保存技能（保持不变）
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

  // —— 保存（名称/元素/定位/标签 + 六维 一次性提交；不再调用 /raw_stats）
  const saveEdit = async () => {
    if (!selected) return
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      await api.put(`/monsters/${selected.id}`, {
        name_final: editName.trim(),
        element: editElement || null,
        role: editRole || null,
        // 直接保存数据库中的六维
        hp, speed, attack, defense, magic, resist,
        // 标签
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(Boolean),
      })

      // 技能
      const filtered = editSkills.filter(s => (s.name || '').trim())
      await saveSkillsWithFallback(selected.id, filtered)

      // 刷新
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

  // —— 一键自动匹配（优先调用后端批量接口，兜底逐条）
  const autoMatchBatch = async () => {
    const items = list.data?.items || []
    if (!items.length) return alert('当前没有可处理的记录')
    const target = selectedIds.size ? items.filter(i => selectedIds.has(i.id)) : items
    if (!target.length) return alert('请勾选一些记录，或直接对当前页可见项执行。')
    if (!window.confirm(`将对 ${target.length} 条记录执行“自动匹配”（后端推断定位+建议标签并保存）。是否继续？`)) return

    setAutoMatching(true)
    try {
      try {
        await api.post('/monsters/auto_match', { ids: target.map(x => x.id) })
      } catch (e: any) {
        const ids = target.map(x => x.id)
        for (const id of ids) {
          try { await api.post(`/tags/monsters/${id}/retag`) } catch {}
          try { await api.get(`/monsters/${id}/derived`) } catch {}
        }
      }

      await list.refetch()
      if (selected) {
        const fresh = (await api.get(`/monsters/${selected.id}`)).data as Monster
        setSelected(fresh)
      }
      alert('自动匹配完成')
    } catch (e: any) {
      alert(e?.response?.data?.detail || '自动匹配失败')
    } finally {
      setAutoMatching(false)
    }
  }

  // —— 抽屉内“一键匹配（填充）”
  const fillEditByAutoMatch = async () => {
    if (!selected) return
    const d = (await api.get(`/monsters/${selected.id}/derived`)).data as {
      role_suggested?: string, tags?: string[]
    }
    if (typeof d?.role_suggested === 'string') setEditRole(d.role_suggested)
    if (Array.isArray(d?.tags)) setEditTags(d.tags.join(' '))
    if (!isEditing) setIsEditing(true)
  }

  const elementOptions = ['金','木','水','火','土','风','雷','冰','毒','妖','光','暗','音']

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

        {/* 第二行：元素下拉；排序支持派生字段 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <select className="select" value={element} onChange={e => { setElement(e.target.value); setPage(1) }}>
            <option value="">元素</option>
            {elementOptions.map(el => <option key={el} value={el}>{el}</option>)}
          </select>
          <select className="select" value={tag} onChange={e => { setTag(e.target.value); setPage(1) }}>
            <option value="">标签</option>
            {(localTagCounts || []).map(t => <option key={t.name} value={t.name}>{t.name}（{t.count}）</option>)}
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
              <option value="pp_pressure">PP（派生）</option>
            </select>
            <select className="select" value={order} onChange={e => setOrder(e.target.value as any)}>
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
          </div>
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

      {/* 列表（展示派生五维） */}
      <div className="card">
        <div className="overflow-auto">
          <table className="table">
            <thead>
              <tr>
                <th className="w-8 text-center">
                  <input
                    type="checkbox"
                    aria-label="全选"
                    checked={!!list.data?.items?.length && list.data.items.every(i => selectedIds.has(i.id))}
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
                <th className="text-center">PP</th>
                <th className="text-center">标签</th>
              </tr>
            </thead>
            {list.isLoading && <SkeletonRows rows={8} cols={11} />}
            {!list.isLoading && (
              <tbody>
                {list.data?.items?.map((m: Monster) => (
                  <tr key={m.id}>
                    <td className="text-center">
                      <input type="checkbox" checked={selectedIds.has(m.id)} onChange={() => toggleOne(m.id)} />
                    </td>
                    <td className="text-center">{m.id}</td>
                    <td className="text-left">
                      <button className="text-blue-600 hover:underline" onClick={() => openDetail(m)}>
                        {m.name_final}
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
                        {(m.tags || []).map(t => <span key={t} className="badge">{t}</span>)}
                      </div>
                    </td>
                  </tr>
                ))}
                {list.data?.items?.length === 0 && (
                  <tr>
                    <td colSpan={11} className="text-center text-gray-500 py-6">没有数据。请调整筛选或导入 JSON/CSV。</td>
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

      {/* 详情抽屉 */}
      <SideDrawer open={!!selected} onClose={() => { setSelected(null); setIsEditing(false) }} title={selected?.name_final}>
        {selected && (
          <div className="space-y-5">
            <div className="flex items-center justify-end gap-2">
              {!isEditing ? (
                <>
                  <button className="btn" onClick={async () => {
                    try { await api.get(`/monsters/${selected.id}/derived`) } catch {}
                    enterEdit()
                  }}>编辑</button>
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
                  <div className="flex flex-wrap gap-1 justify-center">
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
                    <div className="md:col-span-2">
                      <label className="label">标签（空格/逗号分隔）</label>
                      <input className="input" value={editTags} onChange={e => setEditTags(e.target.value)} />
                    </div>
                  </div>
                </div>

                <div className="card p-3 space-y-3">
                  <h4 className="font-semibold">基础种族值（原始六维，直接保存到后端）</h4>
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