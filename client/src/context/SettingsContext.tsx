import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'

type Settings = {
  pageSize: number
  setPageSize: (n: number) => void
  crawlLimit: string
  setCrawlLimit: (s: string) => void
}

const SettingsCtx = createContext<Settings | null>(null)

const LS_KEY = 'kb_settings_v1'

function loadFromLS() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return null
    return JSON.parse(raw) as Partial<Settings>
  } catch { return null }
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const saved = loadFromLS()
  const [pageSize, setPageSize] = useState<number>(saved?.pageSize && Number(saved.pageSize) > 0 ? Number(saved.pageSize) : 20)
  const [crawlLimit, setCrawlLimit] = useState<string>(typeof saved?.crawlLimit === 'string' ? saved!.crawlLimit! : '')

  // 持久化
  useEffect(() => {
    localStorage.setItem(LS_KEY, JSON.stringify({ pageSize, crawlLimit }))
  }, [pageSize, crawlLimit])

  const value = useMemo(() => ({ pageSize, setPageSize, crawlLimit, setCrawlLimit }), [pageSize, crawlLimit])
  return <SettingsCtx.Provider value={value}>{children}</SettingsCtx.Provider>
}

export function useSettings() {
  const ctx = useContext(SettingsCtx)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}