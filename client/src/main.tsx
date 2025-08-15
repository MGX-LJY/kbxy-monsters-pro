import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { SettingsProvider } from './context/SettingsContext'   // ← 加这行
import App from './App'
import './styles.css'

const qc = new QueryClient({
  defaultOptions: {
    queries: { retry: 2, staleTime: 5_000 },
  }
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <SettingsProvider>                           {/* ← 用 Provider 包裹整个应用 */}
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </SettingsProvider>
    </QueryClientProvider>
  </React.StrictMode>
)