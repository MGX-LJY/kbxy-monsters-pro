import React from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api'
import { Upload, RefreshCw, Github } from 'lucide-react'

export default function TopBar({ onOpenImport }: { onOpenImport: () => void }) {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await api.get('/health')).data,
  })

  return (
    <header className="sticky top-0 bg-white/80 backdrop-blur z-40 border-b">
      <div className="container py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold">卡布妖怪图鉴 Pro</span>
          <kbd>FastAPI</kbd><span className="text-gray-300">·</span><kbd>React</kbd>
          <span className="text-sm text-gray-500">API OK · {health.data?.counts?.monsters ?? 0}</span>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn" onClick={() => health.refetch()}><RefreshCw className="w-4 h-4 mr-1" />刷新</button>
          <a className="btn" href="https://github.com" target="_blank"><Github className="w-4 h-4 mr-1" />GitHub</a>
          <button className="btn btn-primary" onClick={onOpenImport}><Upload className="w-4 h-4 mr-1" />导入 CSV</button>
        </div>
      </div>
    </header>
  )
}
