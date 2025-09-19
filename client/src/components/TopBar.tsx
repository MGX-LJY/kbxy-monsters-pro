import React from 'react'
import { Github, RefreshCw, Grid2x2, Globe, Clock } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import SettingsButton from './SettingsButton'

export default function TopBar({
  onRefresh,
  onOpenImport,
  onOpenTypeChart,
}: {
  onRefresh: () => void
  onOpenImport?: () => void
  /** 点击"属性克制表"时触发，由父组件打开弹框/侧滑层并拉取后端数据渲染 */
  onOpenTypeChart?: () => void
}) {
  const location = useLocation()
  const navigate = useNavigate()
  
  const handleTimeMachineClick = () => {
    if (location.pathname === '/backup') {
      // 如果当前在备份页面，返回首页
      navigate('/')
    } else {
      // 否则进入备份页面
      navigate('/backup')
    }
  }
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
          {/* 属性克制表 */}
          <button
            className="btn h-9 px-3 hover:bg-gray-100 transition"
            onClick={onOpenTypeChart}
            title="查看属性克制表"
            aria-label="属性克制表"
          >
            <Grid2x2 className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">属性克制表</span>
          </button>

          {/* 新增：获取图鉴（触发全局事件，让 MonstersPage 来执行原有逻辑） */}
          <button
            className="btn h-9 px-3 hover:bg-gray-100 transition"
            onClick={() => window.dispatchEvent(new Event('kb:crawl'))}
            title="获取图鉴"
            aria-label="获取图鉴"
          >
            <Globe className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">获取图鉴</span>
          </button>

          {/* 时光机备份 */}
          <button
            onClick={handleTimeMachineClick}
            className={`btn h-9 px-3 hover:bg-gray-100 transition ${location.pathname === '/backup' ? 'bg-blue-100 text-blue-700' : ''}`}
            title={location.pathname === '/backup' ? '退出' : '进入备份'}
            aria-label="时光机备份"
          >
            <Clock className="w-4 h-4 mr-2" />
            <span className="hidden sm:inline">{location.pathname === '/backup' ? '退出' : '备份'}</span>
          </button>

          {/* 刷新（快捷键 C） */}
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

          {/* 设置 */}
          <SettingsButton />

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