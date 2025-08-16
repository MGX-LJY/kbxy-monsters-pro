// client/src/App.tsx
import React, { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './components/TopBar'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import MonstersPage from './pages/MonstersPage'
import { SettingsProvider } from './context/SettingsContext'
import TypeChartDialog from './components/TypeChartDialog'

export default function App() {
  const qc = useQueryClient()
  const [showTypeChart, setShowTypeChart] = useState(false)

  const onRefresh = () => {
    qc.invalidateQueries({ queryKey: ['monsters'] })
    qc.invalidateQueries({ queryKey: ['tags'] })
    qc.invalidateQueries({ queryKey: ['roles'] })
    qc.invalidateQueries({ queryKey: ['health'] })
    // 额外：顺带把克制表相关的缓存也刷掉（可选）
    qc.invalidateQueries({ queryKey: ['type_elements'] })
    qc.invalidateQueries({ queryKey: ['type_chart'] })
  }

  // ===== 方案 B：全局事件，驱动 .btn 按压/释放动画 + 点击点涟漪坐标 =====
  useEffect(() => {
    const addPressing = (el: HTMLElement | null) => {
      if (!el) return
      el.classList.add('pressing')
    }
    const clearPressing = () => {
      document.querySelectorAll<HTMLElement>('.btn.pressing').forEach((el) => {
        el.classList.remove('pressing')
        el.classList.add('released')
        // 释放后的轻弹动画结束后移除标记类
        window.setTimeout(() => el.classList.remove('released'), 280)
      })
    }

    // 指针按下：记录点击坐标到 CSS 变量，并加 pressing
    const onPointerDown = (e: PointerEvent) => {
      const el = (e.target as HTMLElement)?.closest?.('.btn') as HTMLElement | null
      if (!el) return
      const rect = el.getBoundingClientRect()
      el.style.setProperty('--press-x', `${e.clientX - rect.left}px`)
      el.style.setProperty('--press-y', `${e.clientY - rect.top}px`)
      addPressing(el)
    }

    // 指针释放/取消/离开窗口：触发 released
    const onPointerUp = () => clearPressing()
    const onPointerCancel = () => clearPressing()
    const onBlurWindow = () => clearPressing()

    // 无鼠标操作时的可访问性：键盘 Space/Enter 触发“按压/释放”
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      const el = (document.activeElement as HTMLElement | null)?.closest?.('.btn') as HTMLElement | null
      if (!el) return
      if (e.key === ' ') e.preventDefault() // 阻止空格滚动页面
      // 居中触发涟漪（键盘没有坐标）
      const rect = el.getBoundingClientRect()
      el.style.setProperty('--press-x', `${rect.width / 2}px`)
      el.style.setProperty('--press-y', `${rect.height / 2}px`)
      addPressing(el)
    }
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      clearPressing()
    }

    window.addEventListener('pointerdown', onPointerDown, { passive: true })
    window.addEventListener('pointerup', onPointerUp, { passive: true })
    window.addEventListener('pointercancel', onPointerCancel, { passive: true })
    window.addEventListener('blur', onBlurWindow)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)

    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onPointerCancel)
      window.removeEventListener('blur', onBlurWindow)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [])

  return (
    <ToastProvider>
      <ErrorBoundary>
        {/* 注意：TopBar 需要已新增 onOpenTypeChart 回调并在内部按钮里调用 */}
        <TopBar
          onRefresh={onRefresh}
          onOpenTypeChart={() => setShowTypeChart(true)}
        />

        {/* 这里渲染属性克制表弹框 */}
        <TypeChartDialog
          open={showTypeChart}
          onClose={() => setShowTypeChart(false)}
        />

        <Routes>
          <Route path="/" element={<MonstersPage />} />
        </Routes>
      </ErrorBoundary>
    </ToastProvider>
  )
}