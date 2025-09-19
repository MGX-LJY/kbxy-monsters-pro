import React, { createContext, useContext, useState, ReactNode, useCallback } from 'react'

type ToastMsg = { id: string, text: string }
const Ctx = createContext<{push:(t:string)=>void}>({ push: () => {} })

export function useToast(){ return useContext(Ctx) }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<ToastMsg[]>([])
  const push = useCallback((text: string) => {
    const id = Math.random().toString(36).slice(2)
    setList(prev => [...prev, { id, text }])
    setTimeout(() => setList(prev => prev.filter(x => x.id !== id)), 3000)
  }, [])
  return (
    <Ctx.Provider value={{ push }}>
      {children}
    </Ctx.Provider>
  )
}
