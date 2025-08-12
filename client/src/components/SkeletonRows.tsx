import React from 'react'
export default function SkeletonRows({ rows=5, cols=8 }: { rows?: number, cols?: number }){
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, i) => (
        <tr key={i}>
          {Array.from({ length: cols }).map((_, j) => (
            <td key={j}><div className="h-4 w-full bg-gray-100 animate-pulse rounded" /></td>
          ))}
        </tr>
      ))}
    </tbody>
  )
}
