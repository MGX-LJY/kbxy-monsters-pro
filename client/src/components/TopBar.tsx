import React from 'react'
import { Github, RefreshCw } from 'lucide-react'

export default function TopBar({
  onRefresh,
  // 兼容旧调用方：若父组件还传入 onOpenImport，不会报错，但不再使用
  onOpenImport,
}: {
  onRefresh: () => void
  onOpenImport?: () => void
}) {
  return (
    <header className="sticky top-0 z-40 border-b bg-white/70 backdrop-blur supports-[backdrop-filter]:bg-white/60 shadow-sm">
      <div className="container py-3 px-3 flex items-center justify-between gap-3">
        {/* 左侧：品牌 + 技术标签 */}
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-indigo-600 via-fuchsia-500 to-pink-500 bg-clip-text text-transparent">
            卡布妖怪图鉴 Pro
          </span>
          <div className="hidden sm:flex items-center gap-2">
            <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-700">FastAPI</span>
            <span className="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-700">React</span>
          </div>
        </div>

        {/* 右侧：操作 */}
        <div className="flex items-center gap-2">
          {/* 刷新（带快捷键提示） */}
          <button
            className="btn h-9 px-3 hover:bg-gray-100 transition"
            onClick={onRefresh}
            title="刷新（快捷键 C）"
            aria-label="刷新"
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">刷新</span>
            <kbd className="ml-2 hidden sm:inline rounded border bg-white px-1.5 py-0.5 text-[10px] leading-none text-gray-600">C</kbd>
          </button>

          {/* GitHub */}
          <a
            className="btn h-9 px-3 hover:bg-gray-100 transition"
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            title="在 GitHub 查看"
            aria-label="GitHub"
          >
            <Github className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">GitHub</span>
          </a>
        </div>
      </div>
    </header>
  )
}