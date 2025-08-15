// client/src/components/SettingsButton.tsx
import React, { useState } from 'react'
import { Settings as SettingsIcon } from 'lucide-react'
import Modal from './Modal'
import { useSettings } from '../context/SettingsContext'

export default function SettingsButton() {
  const [open, setOpen] = useState(false)
  const { pageSize, setPageSize, crawlLimit, setCrawlLimit } = useSettings()

  const onSave = () => setOpen(false)

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
            <div className="text-xs text-gray-500 mt-1">点击“获取图鉴”时会带上此上限。</div>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button className="btn" onClick={() => setOpen(false)}>取消</button>
            <button className="btn btn-primary" onClick={onSave}>保存</button>
          </div>
        </div>
      </Modal>
    </>
  )
}