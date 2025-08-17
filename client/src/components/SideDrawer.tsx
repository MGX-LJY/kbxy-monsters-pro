// client/src/components/SideDrawer.tsx
import React, { useEffect, useRef, useState } from 'react'
import ReactDOM from 'react-dom'

export default function SideDrawer({
  open,
  onClose,
  children,
  title,
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  title?: string
}) {
  // 与“一键匹配”一致：最短显示 1s + 500ms 柔和淡出
  const MIN_VISIBLE_MS = 50

  const [mounted, setMounted] = useState(open)
  const [closing, setClosing] = useState(!open)
  const shownAtRef = useRef<number>(0)

  // —— 关键：缓存内容与标题，避免父组件在 onClose 置空后文本先消失 —— //
  const lastChildrenRef = useRef<React.ReactNode>(children)
  const lastTitleRef = useRef<string | undefined>(title)
  if (open) {
    // 打开期间，实时更新缓存
    lastChildrenRef.current = children
    lastTitleRef.current = title
  }

  // 控制挂载/卸载与减缓关闭
  useEffect(() => {
    let t1: number | null = null
    let t2: number | null = null
    let raf: number | null = null

    if (open) {
      setMounted(true)
      setClosing(true)            // 先处于 closing，下一帧切换以触发展示动画
      shownAtRef.current = Date.now()
      raf = requestAnimationFrame(() => setClosing(false))
    } else if (mounted) {
      const since = Date.now() - (shownAtRef.current || Date.now())
      const wait = Math.max(0, MIN_VISIBLE_MS - since)
      t1 = window.setTimeout(() => {
        setClosing(true)          // 触发退场动画（500ms）
        t2 = window.setTimeout(() => setMounted(false), 500)
      }, wait) as any
    }

    return () => {
      if (raf) cancelAnimationFrame(raf)
      if (t1) clearTimeout(t1)
      if (t2) clearTimeout(t2)
    }
  }, [open, mounted])

  // Esc 关闭
  useEffect(() => {
    if (!mounted) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mounted, onClose])

  if (!mounted) return null

  // 关闭过程中使用缓存的 title/children，保证文字跟随抽屉动画
  const displayTitle = open ? title : lastTitleRef.current
  const displayChildren = open ? children : lastChildrenRef.current

  return ReactDOM.createPortal(
    <>
      {/* 背景遮罩：与“一键匹配”一致的淡入淡出 + 轻模糊 */}
      <div
        className={`fixed inset-0 z-40 bg-black/20 backdrop-blur-sm transition-opacity duration-500 ${
          closing ? 'opacity-0' : 'opacity-100'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />
      {/* 右侧抽屉：平移 + 透明度过渡（500ms） */}
      <aside
        className={`fixed top-0 right-0 z-50 h-full w-[420px] max-w-[96vw] bg-white shadow-xl border-l
                    transition-all duration-500 ${
                      closing ? 'translate-x-full opacity-0' : 'translate-x-0 opacity-100'
                    }`}
        role="dialog"
        aria-modal="true"
        aria-label={displayTitle || '详情'}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b flex items-center justify-between">
          <h3 className="text-lg font-semibold truncate">{displayTitle}</h3>
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
        <div className="p-4 overflow-auto h-[calc(100%-64px)]">
          {displayChildren}
        </div>
      </aside>
    </>,
    document.body
  )
}