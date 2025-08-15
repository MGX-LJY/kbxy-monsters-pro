// client/src/components/Modal.tsx
import React, { useEffect } from 'react'
import ReactDOM from 'react-dom'

export default function Modal({
  open,
  onClose,
  children,
  maxWidth = 560, // px
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  maxWidth?: number
}) {
  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return ReactDOM.createPortal(
    <>
      {/* 背景遮罩：半透明 + 模糊 */}
      <div className="modal-backdrop" onClick={onClose} />
      {/* 居中容器 */}
      <div className="modal">
        {/* 弹框本体：轻微玻璃感，阻止冒泡避免点击关闭 */}
        <div
          className="w-full rounded-2xl border border-gray-200 shadow-2xl bg-white/90 backdrop-blur-md p-4"
          style={{ maxWidth }}
          role="dialog"
          aria-modal="true"
          onClick={(e) => e.stopPropagation()}
        >
          {children}
        </div>
      </div>
    </>,
    document.body
  )
}