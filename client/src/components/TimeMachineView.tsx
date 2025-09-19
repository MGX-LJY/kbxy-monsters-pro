// client/src/components/TimeMachineView.tsx
import React, { useState, useEffect, useRef } from 'react'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'

type BackupInfo = {
  name: string
  created_at: string
  type: 'manual' | 'auto'
  size: number
  files_count?: number
  description?: string
}

type TimeMachineViewProps = {
  backups: BackupInfo[]
  onClose: () => void
  onRestore: (backupName: string) => void
}

const BTN_FX = 'transition active:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300'

export default function TimeMachineView({ backups, onClose, onRestore }: TimeMachineViewProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [isAnimating, setIsAnimating] = useState(false)
  const timelineRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // 进入动画
    setIsAnimating(true)
    const timer = setTimeout(() => setIsAnimating(false), 500)
    return () => clearTimeout(timer)
  }, [])

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  const formatDate = (dateStr: string) => {
    try {
      return format(new Date(dateStr), 'yyyy年MM月dd日 HH:mm:ss', { locale: zhCN })
    } catch {
      return dateStr
    }
  }

  const formatRelativeDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const diffHours = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60))
      
      if (diffHours < 1) return '刚刚'
      if (diffHours < 24) return `${diffHours}小时前`
      if (diffHours < 24 * 7) return `${Math.floor(diffHours / 24)}天前`
      if (diffHours < 24 * 30) return `${Math.floor(diffHours / (24 * 7))}周前`
      return `${Math.floor(diffHours / (24 * 30))}个月前`
    } catch {
      return dateStr
    }
  }

  const selectedBackup = backups[selectedIndex]

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
    } else if (e.key === 'ArrowUp' && selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1)
    } else if (e.key === 'ArrowDown' && selectedIndex < backups.length - 1) {
      setSelectedIndex(selectedIndex + 1)
    } else if (e.key === 'Enter' && selectedBackup) {
      handleRestore()
    }
  }

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [selectedIndex, selectedBackup])

  const handleRestore = () => {
    if (selectedBackup) {
      const confirmMsg = `确定要还原到 ${formatDate(selectedBackup.created_at)} 的备份吗？\n\n` +
        `备份名称：${selectedBackup.name}\n` +
        `备份类型：${selectedBackup.type === 'auto' ? '自动备份' : '手动备份'}\n` +
        `备份大小：${formatFileSize(selectedBackup.size)}\n\n` +
        `当前数据将被备份后替换，此操作无法直接撤销。`
      
      if (window.confirm(confirmMsg)) {
        onRestore(selectedBackup.name)
      }
    }
  }

  if (!backups.length) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50">
        <div className="text-center text-white">
          <h2 className="text-2xl font-bold mb-4">🕰️ 时光机</h2>
          <p className="text-gray-300 mb-6">暂无备份记录</p>
          <button className={`btn bg-white text-black ${BTN_FX}`} onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-gradient-to-b from-purple-900 via-blue-900 to-black bg-opacity-95 z-50 overflow-hidden">
      {/* 星空背景效果 */}
      <div className="absolute inset-0">
        {Array.from({ length: 50 }, (_, i) => (
          <div
            key={i}
            className="absolute w-1 h-1 bg-white rounded-full opacity-70 animate-pulse"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 3}s`,
              animationDuration: `${2 + Math.random() * 3}s`,
            }}
          />
        ))}
      </div>

      <div 
        ref={containerRef}
        className={`relative h-full flex transition-all duration-500 ${
          isAnimating ? 'scale-95 opacity-0' : 'scale-100 opacity-100'
        }`}
      >
        {/* 时间轴侧边栏 */}
        <div className="w-80 bg-black bg-opacity-40 backdrop-blur-sm border-r border-white border-opacity-20 overflow-y-auto">
          <div className="p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                🕰️ 时光机
              </h2>
              <button
                className="text-white hover:text-gray-300 text-2xl leading-none"
                onClick={onClose}
              >
                ×
              </button>
            </div>
            
            <div className="space-y-2">
              {backups.map((backup, index) => (
                <div
                  key={backup.name}
                  className={`p-3 rounded-lg cursor-pointer transition-all ${
                    index === selectedIndex
                      ? 'bg-blue-600 bg-opacity-80 text-white shadow-lg'
                      : 'bg-white bg-opacity-10 text-gray-200 hover:bg-white hover:bg-opacity-20'
                  }`}
                  onClick={() => setSelectedIndex(index)}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-sm truncate">
                      {backup.name}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      backup.type === 'auto'
                        ? index === selectedIndex 
                          ? 'bg-green-200 text-green-800'
                          : 'bg-green-900 bg-opacity-50 text-green-300'
                        : index === selectedIndex
                          ? 'bg-blue-200 text-blue-800'
                          : 'bg-blue-900 bg-opacity-50 text-blue-300'
                    }`}>
                      {backup.type === 'auto' ? '自动' : '手动'}
                    </span>
                  </div>
                  <div className="text-xs opacity-75">
                    {formatRelativeDate(backup.created_at)}
                  </div>
                  <div className="text-xs opacity-60">
                    {formatFileSize(backup.size)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 主预览区域 */}
        <div className="flex-1 flex flex-col">
          {/* 顶部操作栏 */}
          <div className="bg-black bg-opacity-30 backdrop-blur-sm border-b border-white border-opacity-20 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-2xl font-bold text-white mb-1">
                  {selectedBackup?.name}
                </h3>
                <div className="text-gray-300 text-sm">
                  {selectedBackup && formatDate(selectedBackup.created_at)}
                </div>
              </div>
              <div className="flex gap-3">
                <button
                  className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors"
                  onClick={handleRestore}
                  disabled={!selectedBackup}
                >
                  🔄 还原到此时间点
                </button>
                <button
                  className="px-4 py-2 bg-gray-700 text-white rounded-lg font-medium hover:bg-gray-600 transition-colors"
                  onClick={onClose}
                >
                  关闭
                </button>
              </div>
            </div>
          </div>

          {/* 备份详情预览 */}
          <div className="flex-1 p-6 overflow-auto">
            {selectedBackup ? (
              <div className="bg-white bg-opacity-10 backdrop-blur-sm rounded-lg p-6">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  <div className="bg-black bg-opacity-20 rounded-lg p-4">
                    <h4 className="text-white font-semibold mb-2">📦 备份信息</h4>
                    <div className="space-y-2 text-sm text-gray-300">
                      <div>名称：{selectedBackup.name}</div>
                      <div>类型：{selectedBackup.type === 'auto' ? '自动备份' : '手动备份'}</div>
                      <div>大小：{formatFileSize(selectedBackup.size)}</div>
                      {selectedBackup.files_count && (
                        <div>文件数：{selectedBackup.files_count}</div>
                      )}
                    </div>
                  </div>
                  
                  <div className="bg-black bg-opacity-20 rounded-lg p-4">
                    <h4 className="text-white font-semibold mb-2">🗓️ 时间信息</h4>
                    <div className="space-y-2 text-sm text-gray-300">
                      <div>创建于：{formatDate(selectedBackup.created_at)}</div>
                      <div>距今：{formatRelativeDate(selectedBackup.created_at)}</div>
                    </div>
                  </div>
                  
                  {selectedBackup.description && (
                    <div className="bg-black bg-opacity-20 rounded-lg p-4">
                      <h4 className="text-white font-semibold mb-2">📝 备份描述</h4>
                      <p className="text-sm text-gray-300">
                        {selectedBackup.description}
                      </p>
                    </div>
                  )}
                </div>
                
                {/* 预览内容区域 */}
                <div className="mt-6 bg-black bg-opacity-20 rounded-lg p-6">
                  <h4 className="text-white font-semibold mb-4">📋 备份内容预览</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-gray-300">
                    <div>
                      <div className="font-medium mb-2">🗃️ 数据库</div>
                      <ul className="space-y-1 pl-4">
                        <li>• 怪物数据</li>
                        <li>• 技能数据</li>
                        <li>• 标签关联</li>
                        <li>• 收藏夹数据</li>
                      </ul>
                    </div>
                    <div>
                      <div className="font-medium mb-2">🖼️ 媒体文件</div>
                      <ul className="space-y-1 pl-4">
                        <li>• 怪物图片</li>
                        <li>• 用户上传的媒体</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center h-64">
                <p className="text-gray-400">选择左侧的备份以查看详情</p>
              </div>
            )}
          </div>
          
          {/* 底部提示 */}
          <div className="bg-black bg-opacity-30 backdrop-blur-sm border-t border-white border-opacity-20 p-4">
            <div className="text-center text-gray-400 text-sm">
              <span className="mr-6">↑↓ 上下选择</span>
              <span className="mr-6">Enter 还原</span>
              <span>Esc 退出</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}