import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import SideDrawer from '../components/SideDrawer'

type RoleCount = { name: string, count: number }
type SkillDTO = { id?:number, name:string, description?:string }
type StatsDTO = { total:number, with_skills:number, tags_total:number }

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
  // 搜索 + 筛选（两行两列：上=标签/定位；下=更新时间/降序）
  const [q, setQ] = useState('')
  const [tag, setTag] = useState('')
  const [role, setRole] = useState('')
  const [sort, setSort] = useState<'updated_at'|'name'|'offense'|'survive'|'control'|'tempo'|'pp'>('updated_at')
  const [order, setOrder] = useState<'asc'|'desc'>('desc')

  // 分页
  const [page, setPage] = useState(1)
  const pageSize = 20

  // 勾选/批量
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  // 详情 & 编辑（就在抽屉内）
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
  const [editSkills, setEditSkills] = useState<SkillDTO[]>([])
  const [saving, setSaving] = useState(false)

  // 列表 & 基础数据
  const list = useQuery({
    queryKey: ['monsters', { q, tag, role, sort, order, page, pageSize }],
    queryFn: async () =>
      (await api.get('/monsters', {
        params: { q: q || undefined, tag: tag || undefined, role: role || undefined, sort, order, page, page_size: pageSize }
      })).data as MonsterListResp
  })
  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => (await api.get('/tags', { params: { with_counts: true } })).data as TagCount[]
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

  // 详情的展示用六维
  const raw = (selected as any)?.explain_json?.raw_stats as
    | { hp:number, speed:number, attack:number, defense:number, magic:number, resist:number, sum:number }
    | undefined
  const showStats = raw || {
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
  const userSummary: string | undefined = (selected as any)?.explain_json?.summary
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

  // —— 删除（DELETE 带 JSON body；失败降级 POST）
  const bulkDelete = async () => {
    if (!selectedIds.size) return
    if (!window.confirm(`确认删除选中的 ${selectedIds.size} 条记录？此操作不可撤销。`)) return
    const ids = Array.from(selectedIds)
    try {
      await api.delete('/monsters/bulk_delete', {
        data: { ids },
        headers: { 'Content-Type': 'application/json' }
      })
    } catch (e:any) {
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

  // —— 抽屉：进入编辑模式并填充
  const openDetail = (m: Monster) => {
    setSelected(m)
    setIsEditing(false)
  }
  const enterEdit = () => {
    if (!selected) return
    setEditName(selected.name_final || '')
    setEditElement(selected.element || '')
    setEditRole(selected.role || '')
    setEditTags((selected.tags || []).join(' '))
    const r = (selected as any)?.explain_json?.raw_stats
    if (r) {
      setHp(r.hp ?? 100); setSpeed(r.speed ?? 100); setAttack(r.attack ?? 100)
      setDefense(r.defense ?? 100); setMagic(r.magic ?? 100); setResist(r.resist ?? 100)
    } else {
      setHp(selected.base_survive ?? 100); setSpeed(selected.base_tempo ?? 100); setAttack(selected.base_offense ?? 100)
      setDefense(selected.base_control ?? 100); setMagic(selected.base_control ?? 100); setResist(selected.base_pp ?? 100)
    }
    setEditSkills((skills.data || []).map(s => ({ name: s.name || '', description: s.description || '' })))
    setIsEditing(true)
  }
  const cancelEdit = () => setIsEditing(false)

  // —— 保存（基础 + 技能）
  const saveEdit = async () => {
    if (!selected) return
    if (!editName.trim()) { alert('请填写名称'); return }
    setSaving(true)
    try {
      // 基础换算
      const base_offense = attack
      const base_survive = hp
      const base_control = (defense + magic) / 2
      const base_tempo = speed
      const base_pp = resist

      // 1) 更新基础与标签
      const payload = {
        name_final: editName.trim(),
        element: editElement || null,
        role: editRole || null,
        base_offense, base_survive, base_control, base_tempo, base_pp,
        tags: editTags.split(/[\s,，、;；]+/).map(s => s.trim()).filter(Boolean),
      }
      await api.put(`/monsters/${selected.id}`, payload)

      // 2) 更新技能（在侧边栏内编辑）
      const filtered = editSkills.filter(s => (s.name || '').trim())
      await api.put(`/monsters/${selected.id}/skills`, { skills: filtered })

      // 刷新
      const fresh = (await api.get(`/monsters/${selected.id}`)).data as Monster
      setSelected(fresh)
      skills.refetch()
      list.refetch()
      setIsEditing(false)
    } catch (e:any) {
      alert(e?.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
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
            {tags.data?.map(t => <option key={t.name} value={t.name}>{t.name}（{t.count}）</option>)}
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
        <div className="mt-3 flex justify-end gap-2">
          <button className="btn" onClick={() => list.refetch()}>刷新</button>
          <button className="btn" onClick={exportCSV}>导出 CSV</button>
          <button className="btn" onClick={exportBackup}>备份 JSON</button>
          <button className="btn" onClick={() => (document.getElementById('restoreInput') as HTMLInputElement)?.click()}>恢复 JSON</button>
          <input id="restoreInput" ref={restoreInputRef} type="file" accept="application/json" className="hidden" onChange={onRestoreFile} />
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
                  <button className="btn" onClick={() => setIsEditing(true)}>编辑</button>
                  <button className="btn" onClick={() => deleteOne(selected.id)}>删除</button>
                </>
              ) : (
                <>
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
                        value={val} onChange={e => (setter as any)(parseInt(e.target.value,10))} className="col-span-4"/>
                      <input className="input py-1" value={val}
                        onChange={e => (setter as any)(parseInt(e.target.value || '0', 10))}/>
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
                                 placeholder={`技能 ${idx+1} 名称`}
                                 onChange={e => setEditSkills(prev => prev.map((x,i)=> i===idx? {...x, name:e.target.value}:x))}/>
                          <button className="btn" onClick={() => setEditSkills(prev => prev.filter((_,i)=>i!==idx))} disabled={editSkills.length===1}>删除</button>
                        </div>
                        <textarea className="input h-24" value={s.description || ''} placeholder="技能描述"
                                  onChange={e => setEditSkills(prev => prev.map((x,i)=> i===idx? {...x, description:e.target.value}:x))}/>
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