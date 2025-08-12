import React, { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import TopBar from './components/TopBar'
import { ToastProvider } from './components/Toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import MonstersPage from './pages/MonstersPage'
import Modal from './components/Modal'
import ImportWizard from './components/ImportWizard'

export default function App() {
  const [openImport, setOpenImport] = useState(false)

  return (
    <ToastProvider>
      <ErrorBoundary>
        <TopBar onOpenImport={() => setOpenImport(true)} />
        <Routes>
          <Route path="/" element={<MonstersPage />} />
        </Routes>

        {/* 全局导入弹窗：按钮点了就能打开 */}
        <Modal open={openImport} onClose={() => setOpenImport(false)}>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xl font-semibold">导入 CSV</h2>
            <button className="btn" onClick={() => setOpenImport(false)}>关闭</button>
          </div>
          <ImportWizard />
        </Modal>
      </ErrorBoundary>
    </ToastProvider>
  )
}