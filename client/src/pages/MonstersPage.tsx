import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Monster, MonsterListResp, TagCount } from '../types'
import SkeletonRows from '../components/SkeletonRows'
import Pagination from '../components/Pagination'
import ImportWizard from '../components/ImportWizard'

export default function MonstersPage(){
  const [q, setQ] = useState('')
  const [tag, setTag] = useState('')
  const [sort, setSort] = useState<'updated_at'|'name'|'offense'|'survive'|'control'|'tempo'|'pp'>('updated_at')
  const [order, setOrder] = useState<'asc'|'desc'>('desc')
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [openImport, setOpenImport] = useState(false)

  const list = useQuery({
    queryKey: ['monsters', { q, tag, sort, order, page, pageSize }],
    queryFn: async () => (await api.get('/monsters', { params: { q: q || undefined, tag: tag || undefined, sort, order, page, page_size: pageSize } })).data as MonsterListResp
  })

  const tags = useQuery({
    queryKey: ['tags'],
    queryFn: async () => (await api.get('/tags', { params: { with_counts: true } })).data as TagCount[]
  })

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
                    <td className="font-medium">{m.name_final}</td>
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
                  <tr><td colSpan={10} className="text-center text-gray-500 py-6">没有数据。请尝试清空筛选或点击右上角“导入 CSV”。</td></tr>
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

      {openImport && (
        <div className="modal">
          <div className="modal-backdrop" onClick={()=>setOpenImport(false)} />
          <div className="card w-[920px] max-h-[85vh] overflow-auto">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-semibold">导入 CSV</h2>
              <button className="btn" onClick={()=>setOpenImport(false)}>关闭</button>
            </div>
            <ImportWizard />
          </div>
        </div>
      )}
    </div>
  )
}
