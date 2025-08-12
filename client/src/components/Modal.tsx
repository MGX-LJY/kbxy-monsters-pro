import React from 'react'

export default function Modal({ open, onClose, children, className='' }: { open: boolean, onClose: () => void, children: React.ReactNode, className?: string }){
  if(!open) return null
  return (
    <div className="modal">
      <div className="modal-backdrop" onClick={onClose} />
      <div className={"card w-[920px] max-h-[85vh] overflow-auto relative " + className}>
        <button className="btn absolute right-3 top-3" onClick={onClose}>关闭</button>
        {children}
      </div>
    </div>
  )
}
