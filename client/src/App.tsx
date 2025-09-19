import React, { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './components/TopBar'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import MonstersPage from './pages/MonstersPage'
import BackupPage from './pages/BackupPage'
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
    qc.invalidateQueries({ queryKey: ['type_elements'] })
    qc.invalidateQueries({ queryKey: ['type_chart'] })
  }

  useEffect(() => {
    const addPressing = (el: HTMLElement | null) => {
      if (!el) return
      el.classList.add('pressing')
    }
    const clearPressing = () => {
      document.querySelectorAll<HTMLElement>('.btn.pressing').forEach((el) => {
        el.classList.remove('pressing')
        el.classList.add('released')
        window.setTimeout(() => el.classList.remove('released'), 280)
      })
    }

    const onPointerDown = (e: PointerEvent) => {
      const el = (e.target as HTMLElement)?.closest?.('.btn') as HTMLElement | null
      if (!el) return
      const rect = el.getBoundingClientRect()
      el.style.setProperty('--press-x', `${e.clientX - rect.left}px`)
      el.style.setProperty('--press-y', `${e.clientY - rect.top}px`)
      addPressing(el)
    }

    const onPointerUp = () => clearPressing()
    const onPointerCancel = () => clearPressing()
    const onBlurWindow = () => clearPressing()

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      const el = (document.activeElement as HTMLElement | null)?.closest?.('.btn') as HTMLElement | null
      if (!el) return
      if (e.key === ' ') e.preventDefault()
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
        <TopBar
          onRefresh={onRefresh}
          onOpenTypeChart={() => setShowTypeChart(true)}
        />

        <TypeChartDialog
          open={showTypeChart}
          onClose={() => setShowTypeChart(false)}
        />

        <Routes>
          <Route path="/" element={<MonstersPage />} />
          <Route path="/backup" element={<BackupPage />} />
        </Routes>
      </ErrorBoundary>
    </ToastProvider>
  )
}