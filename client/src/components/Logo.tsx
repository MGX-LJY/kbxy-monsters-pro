// client/src/components/Logo.tsx
import React from 'react'

interface LogoProps {
  size?: number | string
  className?: string
  showText?: boolean
  variant?: 'full' | 'icon' | 'horizontal'
  onClick?: () => void
}

export default function Logo({ 
  size = 40, 
  className = '', 
  showText = false,
  variant = 'icon',
  onClick
}: LogoProps) {
  
  const LogoIcon = ({ size: iconSize }: { size: number | string }) => (
    <img 
      src="/logo.png" 
      alt="卡布妖怪图鉴Pro"
      width={iconSize} 
      height={iconSize}
      className="inline-block"
      style={{ objectFit: 'contain' }}
    />
  )

  if (variant === 'icon') {
    return (
      <div className={className} onClick={onClick}>
        <LogoIcon size={size} />
      </div>
    )
  }

  if (variant === 'horizontal') {
    return (
      <div className={`flex items-center gap-3 ${className}`} onClick={onClick}>
        <LogoIcon size={size} />
        {showText && (
          <div className="flex flex-col">
            <span className="text-lg font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">
              卡布妖怪图鉴
            </span>
            <span className="text-xs text-red-600 font-semibold">PRO</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={`flex flex-col items-center gap-2 ${className}`} onClick={onClick}>
      <LogoIcon size={size} />
      {showText && (
        <div className="text-center">
          <div className="text-lg font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">
            卡布妖怪图鉴
          </div>
          <div className="text-xs text-red-600 font-semibold">PRO</div>
        </div>
      )}
    </div>
  )
}