import React, { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import TopBar from './components/TopBar'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import MonstersPage from './pages/MonstersPage'

export default function App(){
  const [openImport, setOpenImport] = useState(false)
  return (
    <ToastProvider>
      <ErrorBoundary>
        <TopBar onOpenImport={() => setOpenImport(true)} />
        <Routes>
          <Route path="/" element={<MonstersPage />} />
        </Routes>
      </ErrorBoundary>
    </ToastProvider>
  )
}
