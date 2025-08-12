import React from 'react'

type Chip = {
  label: string
  onRemove: () => void
}

type Props = {
  chips: Chip[]
  onClearAll?: () => void
}

export default function FilterChips({ chips, onClearAll }: Props) {
  if (!chips.length) return null
  return (
    <div className="mt-2 -mb-1">
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">已选过滤（{chips.length}）</div>
        <button
          className="text-sm text-gray-500 hover:text-gray-700"
          onClick={onClearAll}
        >
          清空
        </button>
      </div>
      <div className="mt-2 overflow-x-auto">
        <div className="flex gap-2 pb-1">
          {chips.map((c, i) => (
            <span key={i} className="badge inline-flex items-center gap-1">
              {c.label}
              <button
                className="text-gray-500 hover:text-gray-800"
                aria-label="移除过滤"
                onClick={c.onRemove}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}