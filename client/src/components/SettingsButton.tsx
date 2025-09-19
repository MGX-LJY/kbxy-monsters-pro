// client/src/components/SettingsButton.tsx
import React, { useState } from 'react'
import { Settings as SettingsIcon, Save } from 'lucide-react'
import Modal from './Modal'
import { useSettings } from '../context/SettingsContext'

export default function SettingsButton() {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const { 
    pageSize, setPageSize, 
    crawlLimit, setCrawlLimit,
    backupSettings, setBackupSettings,
    updateBackupConfig
  } = useSettings()

  const onSave = async () => {
    setSaving(true)
    try {
      await updateBackupConfig()
      setOpen(false)
    } catch (error) {
      console.error('Failed to save backup settings:', error)
      // 可以在这里添加错误提示
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <button
        className="btn h-9 px-3 hover:bg-gray-100 transition"
        onClick={() => setOpen(true)}
        title="设置"
        aria-label="设置"
      >
        <SettingsIcon className="w-4 h-4 mr-2" />
        <span className="hidden sm:inline">设置</span>
      </button>

      <Modal open={open} onClose={() => setOpen(false)}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">偏好设置</h2>
          <button className="btn" onClick={() => setOpen(false)}>关闭</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label">每页显示数量</label>
            <select
              className="select"
              value={pageSize}
              onChange={e => setPageSize(Math.max(1, Number(e.target.value)))}
            >
              {[10, 20, 30, 50, 100, 200].map(n => (
                <option key={n} value={n}>{n} 条/页</option>
              ))}
            </select>
            <div className="text-xs text-gray-500 mt-1">影响列表分页 size，并会记住你的选择。</div>
          </div>

          <div>
            <label className="label">图鉴爬取数量上限（可留空）</label>
            <input
              className="input"
              placeholder="例如 200；留空=尽可能多"
              value={crawlLimit}
              onChange={e => setCrawlLimit(e.target.value.replace(/[^\d]/g, ''))}
            />
            <div className="text-xs text-gray-500 mt-1">点击"获取图鉴"时会带上此上限。</div>
          </div>

          {/* 时光机备份设置 */}
          <div className="border-t pt-4">
            <h3 className="font-medium mb-3">🕰️ 时光机自动备份</h3>
            
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="auto-backup"
                  className="rounded"
                  checked={backupSettings.auto_backup_enabled}
                  onChange={e => setBackupSettings({
                    ...backupSettings,
                    auto_backup_enabled: e.target.checked
                  })}
                />
                <label htmlFor="auto-backup" className="text-sm">启用自动备份</label>
              </div>

              <div>
                <label className="label">备份间隔时间</label>
                <select
                  className="select"
                  value={backupSettings.backup_interval_hours}
                  onChange={e => setBackupSettings({
                    ...backupSettings,
                    backup_interval_hours: Number(e.target.value)
                  })}
                >
                  <option value={1}>每小时</option>
                  <option value={6}>每6小时</option>
                  <option value={12}>每12小时</option>
                  <option value={24}>每天</option>
                  <option value={72}>每3天</option>
                  <option value={168}>每周</option>
                </select>
                <div className="text-xs text-gray-500 mt-1">自动备份的时间间隔。</div>
              </div>

              <div>
                <label className="label">最多保留备份数量</label>
                <select
                  className="select"
                  value={backupSettings.max_backups}
                  onChange={e => setBackupSettings({
                    ...backupSettings,
                    max_backups: Number(e.target.value)
                  })}
                >
                  <option value={5}>5个</option>
                  <option value={10}>10个</option>
                  <option value={20}>20个</option>
                  <option value={30}>30个</option>
                  <option value={50}>50个</option>
                  <option value={100}>100个</option>
                </select>
                <div className="text-xs text-gray-500 mt-1">超过此数量时会自动删除最旧的备份。</div>
              </div>
            </div>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button className="btn" onClick={() => setOpen(false)}>取消</button>
            <button 
              className="btn btn-primary flex items-center gap-2" 
              onClick={onSave}
              disabled={saving}
            >
              {saving ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  保存中...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  保存
                </>
              )}
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}