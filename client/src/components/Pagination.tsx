import React from 'react'

export default function Pagination({ page, pageSize, total, onPageChange }: { page: number, pageSize: number, total: number, onPageChange: (p:number)=>void }){
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center gap-2">
      <button className="btn" disabled={page<=1} onClick={()=>onPageChange(page-1)}>上一页</button>
      <span className="text-sm text-gray-600">第 {page} / {totalPages} 页 · 共 {total} 条</span>
      <button className="btn" disabled={page>=totalPages} onClick={()=>onPageChange(page+1)}>下一页</button>
    </div>
  )
}
