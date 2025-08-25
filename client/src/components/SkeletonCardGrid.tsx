// client/src/components/SkeletonCardGrid.tsx
import React from 'react'

type Props = {
  /** 骨架数量（默认 12） */
  count?: number
  /** 网格断点（可选，与 MonsterCardGrid 保持一致） */
  className?: string
}

const gridClassesDefault =
  'grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 gap-4'

export default function SkeletonCardGrid({ count = 12, className }: Props) {
  const gridCls = [gridClassesDefault, className].filter(Boolean).join(' ')
  return (
    <div className={gridCls}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded-2xl border border-gray-100 bg-white overflow-hidden"
        >
          <div className="aspect-[4/3] w-full bg-gray-100 animate-pulse" />
          <div className="p-3 space-y-2">
            <div className="h-4 w-2/3 mx-auto rounded bg-gray-100 animate-pulse" />
            <div className="flex items-center justify-center gap-2">
              <div className="h-4 w-12 rounded bg-gray-100 animate-pulse" />
              <div className="h-4 w-12 rounded bg-gray-100 animate-pulse" />
            </div>
            <div className="h-4 w-24 mx-auto rounded bg-gray-100 animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  )
}