// client/src/components/Modal.tsx
import React, { useEffect, useRef, useState } from 'react'
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
  // 与“一键匹配”一致：最短显示 1000ms，淡出 500ms
  const MIN_VISIBLE_MS = 1000
  const CLOSE_DURATION_MS = 500

  // 挂载控制 + 进入/离开动画状态
  const [mounted, setMounted] = useState(open)
  const [closing, setClosing] = useState(false)
  const shownAtRef = useRef(0)

  // 同步 open：打开时先挂载并在下一帧淡入；关闭时先等待最短显示，再淡出，动画结束后卸载
  useEffect(() => {
    if (open) {
      setMounted(true)
      setClosing(true)                // 初始先处于“收起”态
      shownAtRef.current = Date.now()
      const raf = requestAnimationFrame(() => setClosing(false)) // 下一帧淡入
      return () => cancelAnimationFrame(raf)
    }
    if (!open && mounted) {
      const since = Date.now() - (shownAtRef.current || Date.now())
      const wait = Math.max(0, MIN_VISIBLE_MS - since)
      const t1 = setTimeout(() => {
        setClosing(true)              // 开始淡出
        const t2 = setTimeout(() => setMounted(false), CLOSE_DURATION_MS)
        return () => clearTimeout(t2)
      }, wait)
      return () => clearTimeout(t1)
    }
  }, [open, mounted])

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!mounted) return null

  return ReactDOM.createPortal(
    <div
      className={`fixed inset-0 z-50 backdrop-blur-sm bg-black/20 flex items-center justify-center
                  transition-opacity duration-500 ${closing ? 'opacity-0' : 'opacity-100'}`}
      onClick={onClose}
      role="presentation"
    >
      <div
        className={`w-[92vw] rounded-2xl shadow-xl p-4 bg-white
                    transition-all duration-500 ${closing ? 'opacity-0 scale-95' : 'opacity-100 scale-100'}`}
        style={{ maxWidth }}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body
  )
}