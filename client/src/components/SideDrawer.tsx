import React from 'react'

export default function SideDrawer({
  open, onClose, children, title
}: { open: boolean, onClose: () => void, children: React.ReactNode, title?: string }) {
  return (
    <>
      <div
        className={`fixed inset-0 bg-black/30 transition ${open ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}
        onClick={onClose}
      />
      <aside
        className={`fixed top-0 right-0 h-full w-[420px] bg-white shadow-xl border-l transition-transform duration-200
                    ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        <div className="p-4 border-b flex items-center justify-between">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
        <div className="p-4 overflow-auto h-[calc(100%-64px)]">
          {children}
        </div>
      </aside>
    </>
  )
}