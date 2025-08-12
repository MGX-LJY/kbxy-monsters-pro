import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import SideDrawer from '../components/SideDrawer'

export default function MonstersPage() {
  const [q, setQ] = useState('')
  const [tag, setTag] = useState('')
  const [sort, setSort] = useState<'updated_at'|'name'|'offense'|'survive'|'control'|'tempo'|'pp'>('updated_at')
  const [order, setOrder] = useState<'asc'|'desc'>('desc')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Monster | null>(null)
  const pageSize = 20

  const list = useQuery({
    queryKey: ['monsters', { q, tag, sort, order, page, pageSize }],
    queryFn: async () =>
      (await api.get('/monsters', {
        params: { q: q || undefined, tag: tag || undefined, sort, order, page, page_size: pageSize }
      })).data as MonsterListResp
  })

  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => (await api.get('/tags', { params: { with_counts: true } })).data as TagCount[]
  })

  // 侧边栏：技能列表
  const skills = useQuery({
    queryKey: ['skills', selected?.id],
    enabled: !!selected?.id,
    queryFn: async () => (await api.get(`/monsters/${selected!.id}/skills`)).data as {id:number,name:string,description:string}[]
  })

  // 便捷读取 raw_stats（如果没有，则用 base_* 兜底）
  const raw = (selected as any)?.explain_json?.raw_stats as
    | { hp:number, speed:number, attack:number, defense:number, magic:number, resist:number, sum:number }
    | undefined

  const showStats = raw || {
    hp: selected?.base_survive ?? 0,
    speed: selected?.base_tempo ?? 0,
    attack: selected?.base_offense ?? 0,
    defense: selected?.base_control ?? 0, // 兜底（平均值时仅供参考）
    magic: selected?.base_control ?? 0,
    resist: selected?.base_pp ?? 0,
    sum: (selected?.base_survive ?? 0) + (selected?.base_tempo ?? 0) + (selected?.base_offense ?? 0) +
         (selected?.base_control ?? 0) + (selected?.base_control ?? 0) + (selected?.base_pp ?? 0),
  }

  // 技能兜底：接口为空则使用 explain_json.skill_names
  const fallbackSkillNames: string[] = (selected as any)?.explain_json?.skill_names || []

  return (
    <div className="container my-6 space-y-4">
      <div className="card grid grid-cols-1 md:grid-cols-4 gap-3">
        <input className="input md:col-span-2" placeholder="搜索名称..." value={q} onChange={e => { setQ(e.target.value); setPage(1) }} />
        <select className="select" value={tag} onChange={e => { setTag(e.target.value); setPage(1) }}>
          <option value="">全部标签</option>
          {tags.data?.map(t => <option key={t.name} value={t.name}>{t.name}（{t.count}）</option>)}
        </select>
        <div className="flex gap-2">
          <select className="select" value={sort} onChange={e => setSort(e.target.value as any)}>
            <option value="updated_at">更新时间</option>
            <option value="name">名称</option>
            <option value="offense">攻</option>
            <option value="survive">生</option>
            <option value="control">控</option>
            <option value="tempo">速</option>
            <option value="pp">PP</option>
          </select>
          <select className="select" value={order} onChange={e => setOrder(e.target.value as any)}>
            <option value="desc">降序</option>
            <option value="asc">升序</option>
          </select>
        </div>
      </div>

      <div className="card">
        <div className="overflow-auto">
          <table className="table">
            <thead>
              <tr>
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
            {list.isLoading && <SkeletonRows rows={8} cols={10} />}
            {!list.isLoading && (
              <tbody>
                {list.data?.items?.map((m: Monster) => (
                  <tr key={m.id}>
                    <td>{m.id}</td>
                    <td>
                      <button className="text-blue-600 hover:underline" onClick={() => setSelected(m)}>
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
                    <td className="space-x-1">{m.tags?.map(t => <span key={t} className="badge">{t}</span>)}</td>
                  </tr>
                ))}
                {list.data?.items?.length === 0 && (
                  <tr><td colSpan={10} className="text-center text-gray-500 py-6">没有数据。请清空筛选或使用右上角“导入 CSV”。</td></tr>
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

      <SideDrawer open={!!selected} onClose={() => setSelected(null)} title={selected?.name_final}>
        {selected && (
          <div className="space-y-4">
            <div>
              <h4 className="font-semibold mb-2">基础种族值（六维）</h4>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="p-2 bg-gray-50 rounded">体力：<b>{showStats.hp}</b></div>
                <div className="p-2 bg-gray-50 rounded">速度：<b>{showStats.speed}</b></div>
                <div className="p-2 bg-gray-50 rounded">攻击：<b>{showStats.attack}</b></div>
                <div className="p-2 bg-gray-50 rounded">防御：<b>{showStats.defense}</b></div>
                <div className="p-2 bg-gray-50 rounded">法术：<b>{showStats.magic}</b></div>
                <div className="p-2 bg-gray-50 rounded">抗性：<b>{showStats.resist}</b></div>
                <div className="p-2 bg-gray-100 rounded col-span-2 text-center">六维总和：<b>{showStats.sum}</b></div>
              </div>
            </div>

            <div>
              <h4 className="font-semibold mb-2">技能</h4>
              {!skills.data?.length && !fallbackSkillNames.length && (
                <div className="text-sm text-gray-500">暂无技能数据</div>
              )}
              <ul className="space-y-2">
                {skills.data?.map(s => (
                  <li key={s.id} className="p-2 bg-gray-50 rounded">
                    <div className="font-medium">{s.name}</div>
                    {s.description && <div className="text-sm text-gray-600">{s.description}</div>}
                  </li>
                ))}
                {!skills.data?.length && fallbackSkillNames.map((n, i) => (
                  <li key={i} className="p-2 bg-gray-50 rounded">
                    <div className="font-medium">{n}</div>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h4 className="font-semibold mb-2">标签</h4>
              <div className="space-x-1">
                {selected.tags?.map(t => <span key={t} className="badge">{t}</span>)}
              </div>
            </div>
          </div>
        )}
      </SideDrawer>
    </div>
  )
}