// client/src/components/TypeChartModal.tsx
import React from 'react'
import Modal from './Modal'

export default function TypeChartModal({
  open,
  onClose,
  children,
  title = '属性克制表',
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  title?: string
}) {
  return (
    <Modal open={open} onClose={onClose}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button className="btn" onClick={onClose}>关闭</button>
      </div>
      {/* 把你原来“属性克制表”的内容塞到 children 里 */}
      {children}
    </Modal>
  )
}