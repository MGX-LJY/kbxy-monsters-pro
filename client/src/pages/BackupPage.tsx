// client/src/pages/BackupPage.tsx
import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { backupApi } from '../api'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import TimeMachineView from '../components/TimeMachineView'

type BackupInfo = {
  name: string
  created_at: string
  type: 'manual' | 'auto'
  size: number
  files_count?: number
  description?: string
}

type BackupConfig = {
  auto_backup_enabled: boolean
  backup_interval_hours: number
  max_backups: number
  last_backup_time?: string
}

const BTN_FX = 'transition active:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300'

export default function BackupPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [showTimeMachine, setShowTimeMachine] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)

  // 获取备份列表
  const { data: backupList, isLoading } = useQuery({
    queryKey: ['backups'],
    queryFn: async () => {
      const { data } = await backupApi.listBackups()
      return data
    },
  })

  // 获取备份状态
  const { data: status } = useQuery({
    queryKey: ['backup-status'],
    queryFn: async () => {
      const { data } = await backupApi.getStatus()
      return data
    },
    refetchInterval: 30000, // 每30秒刷新一次
  })

  // 获取备份配置
  const { data: config } = useQuery({
    queryKey: ['backup-config'],
    queryFn: async () => {
      const { data } = await backupApi.getConfig()
      return data as BackupConfig
    },
  })

  // 创建备份
  const createBackupMutation = useMutation({
    mutationFn: (data: { name?: string; description?: string }) => 
      backupApi.createBackup(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backups'] })
      queryClient.invalidateQueries({ queryKey: ['backup-status'] })
      setShowCreateForm(false)
      setCreateName('')
      setCreateDescription('')
      alert('备份创建成功！')
    },
    onError: (error: any) => {
      console.error('Backup creation failed:', error)
      alert(`备份创建失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // 删除备份
  const deleteBackupMutation = useMutation({
    mutationFn: (backupName: string) => backupApi.deleteBackup(backupName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backups'] })
      queryClient.invalidateQueries({ queryKey: ['backup-status'] })
    },
  })

  // 还原备份
  const restoreBackupMutation = useMutation({
    mutationFn: (backupName: string) => backupApi.restoreBackup(backupName),
    onSuccess: () => {
      alert('备份还原成功！请刷新页面查看结果。')
    },
    onError: (error: any) => {
      alert(`还原失败: ${error.response?.data?.message || error.message}`)
    },
  })

  // 触发自动备份
  const autoBackupMutation = useMutation({
    mutationFn: () => backupApi.triggerAutoBackup(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['backups'] })
      queryClient.invalidateQueries({ queryKey: ['backup-status'] })
      if (data.data.created) {
        alert(`自动备份创建成功: ${data.data.backup_info?.name}`)
      } else {
        alert('自动备份未启用或时间间隔未到')
      }
    },
    onError: (error: any) => {
      console.error('Auto backup failed:', error)
      alert(`自动备份失败: ${error.response?.data?.detail || error.message}`)
    },
  })

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

  const handleCreateBackup = (e: React.FormEvent) => {
    e.preventDefault()
    createBackupMutation.mutate({
      name: createName.trim() || undefined,
      description: createDescription.trim() || undefined,
    })
  }

  const handleDeleteBackup = (backupName: string) => {
    if (window.confirm('确定要删除这个备份吗？此操作无法撤销。')) {
      deleteBackupMutation.mutate(backupName)
    }
  }

  const handleRestoreBackup = (backupName: string) => {
    if (window.confirm('确定要还原这个备份吗？当前数据将被备份并替换。')) {
      restoreBackupMutation.mutate(backupName)
    }
  }

  if (showTimeMachine) {
    return (
      <TimeMachineView 
        backups={backupList?.backups || []}
        onClose={() => setShowTimeMachine(false)}
        onRestore={handleRestoreBackup}
      />
    )
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <button
            onClick={() => navigate('/')}
            className={`btn ${BTN_FX} flex items-center gap-2 hover:bg-gray-100`}
            title="返回主页"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">返回</span>
          </button>
          <h1 className="text-2xl font-bold">🕰️ 时光机备份</h1>
        </div>
        <p className="text-gray-600">管理您的数据备份，支持自动备份和手动还原</p>
      </div>

      {/* 状态卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-gray-500">总备份数</h3>
          <p className="text-2xl font-bold text-blue-600">{status?.total_backups || 0}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-gray-500">占用空间</h3>
          <p className="text-2xl font-bold text-green-600">
            {status?.total_size ? formatFileSize(status.total_size) : '0 B'}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-gray-500">自动备份</h3>
          <p className={`text-2xl font-bold ${
            status?.auto_backup_enabled ? 'text-green-600' : 'text-gray-400'
          }`}>
            {status?.auto_backup_enabled ? '已启用' : '已禁用'}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-gray-500">最后备份</h3>
          <p className="text-sm font-bold text-gray-700">
            {status?.last_backup_time 
              ? formatDate(status.last_backup_time)
              : '从未备份'
            }
          </p>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-3 mb-6">
        <button
          className={`btn btn-primary ${BTN_FX}`}
          onClick={() => setShowCreateForm(true)}
          disabled={createBackupMutation.isPending}
        >
          {createBackupMutation.isPending ? '创建中...' : '📦 创建备份'}
        </button>
        
        <button
          className={`btn ${BTN_FX}`}
          onClick={() => autoBackupMutation.mutate()}
          disabled={autoBackupMutation.isPending}
        >
          {autoBackupMutation.isPending ? '处理中...' : '🔄 立即自动备份'}
        </button>
        
        <button
          className={`btn ${BTN_FX}`}
          onClick={() => setShowTimeMachine(true)}
          disabled={!backupList?.backups?.length}
        >
          🕰️ 时光机还原
        </button>
      </div>

      {/* 创建备份表单 */}
      {showCreateForm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md mx-4">
            <h3 className="text-lg font-bold mb-4">创建新备份</h3>
            <form onSubmit={handleCreateBackup}>
              <div className="mb-4">
                <label className="block text-sm font-medium mb-1">备份名称（可选）</label>
                <input
                  type="text"
                  className="w-full border border-gray-300 rounded px-3 py-2"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="留空则自动生成"
                />
              </div>
              <div className="mb-6">
                <label className="block text-sm font-medium mb-1">备份描述（可选）</label>
                <textarea
                  className="w-full border border-gray-300 rounded px-3 py-2 resize-none"
                  rows={3}
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="描述这次备份的目的..."
                />
              </div>
              <div className="flex gap-3 justify-end">
                <button
                  type="button"
                  className={`btn ${BTN_FX}`}
                  onClick={() => setShowCreateForm(false)}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className={`btn btn-primary ${BTN_FX}`}
                  disabled={createBackupMutation.isPending}
                >
                  {createBackupMutation.isPending ? '创建中...' : '创建备份'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 备份列表 */}
      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b">
          <h2 className="text-lg font-semibold">备份历史</h2>
        </div>
        
        {isLoading ? (
          <div className="p-6 text-center text-gray-500">
            加载中...
          </div>
        ) : !backupList?.backups?.length ? (
          <div className="p-6 text-center text-gray-500">
            暂无备份记录
          </div>
        ) : (
          <div className="divide-y">
            {backupList.backups.map((backup: BackupInfo) => (
              <div key={backup.name} className="p-6 hover:bg-gray-50">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="font-medium">{backup.name}</h3>
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        backup.type === 'auto' 
                          ? 'bg-green-100 text-green-700' 
                          : 'bg-blue-100 text-blue-700'
                      }`}>
                        {backup.type === 'auto' ? '自动' : '手动'}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 space-y-1">
                      <div>创建时间：{formatDate(backup.created_at)}</div>
                      <div>大小：{formatFileSize(backup.size)}</div>
                      {backup.files_count && (
                        <div>文件数量：{backup.files_count}</div>
                      )}
                      {backup.description && (
                        <div>描述：{backup.description}</div>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2 ml-4">
                    <button
                      className={`btn btn-sm ${BTN_FX}`}
                      onClick={() => handleRestoreBackup(backup.name)}
                      disabled={restoreBackupMutation.isPending}
                    >
                      ↶ 还原
                    </button>
                    <button
                      className={`btn btn-sm btn-danger ${BTN_FX}`}
                      onClick={() => handleDeleteBackup(backup.name)}
                      disabled={deleteBackupMutation.isPending}
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}