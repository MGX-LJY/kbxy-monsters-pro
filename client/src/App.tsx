import React, { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import TopBar from './components/TopBar'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import MonstersPage from './pages/MonstersPage'
import { SettingsProvider } from './context/SettingsContext'

export default function App() {
  const qc = useQueryClient()
  const onRefresh = () => {
    qc.invalidateQueries({ queryKey: ['monsters'] })
    qc.invalidateQueries({ queryKey: ['tags'] })
    qc.invalidateQueries({ queryKey: ['roles'] })
    qc.invalidateQueries({ queryKey: ['health'] })
  }

  return (
    <ToastProvider>
      <ErrorBoundary>
        <SettingsProvider>
          <TopBar onRefresh={onRefresh} />
          <Routes>
            <Route path="/" element={<MonstersPage />} />
          </Routes>
        </SettingsProvider>
      </ErrorBoundary>
    </ToastProvider>
  )
}