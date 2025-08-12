import React from 'react'
import { Github, RefreshCw, Upload } from 'lucide-react'

export default function TopBar({
  onOpenImport,
  onRefresh,
}: {
  onOpenImport: () => void
  onRefresh: () => void
}) {
  return (
    <header className="sticky top-0 bg-white/80 backdrop-blur z-40 border-b">
      <div className="container py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold">卡布妖怪图鉴 Pro</span>
          <kbd>FastAPI</kbd><span className="text-gray-300">·</span><kbd>React</kbd>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn" onClick={onRefresh}>
            <RefreshCw className="w-4 h-4 mr-1" />刷新
          </button>
          <a className="btn" href="https://github.com" target="_blank" rel="noreferrer">
            <Github className="w-4 h-4 mr-1" />GitHub
          </a>
          <button className="btn btn-primary" onClick={onOpenImport}>
            <Upload className="w-4 h-4 mr-1" />导入 CSV
          </button>
        </div>
      </div>
    </header>
  )
}