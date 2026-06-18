export function SkeletonRow({ cols = 8 }) {
  return (
    <tr className="animate-pulse">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-3 py-3">
          <div className="h-4 bg-surface-alt rounded" style={{ width: `${60 + (i * 17) % 40}%` }} />
        </td>
      ))}
    </tr>
  )
}

export function SkeletonCard() {
  return (
    <div className="animate-pulse space-y-3 p-4">
      <div className="h-5 bg-surface-alt rounded w-1/3" />
      <div className="h-4 bg-surface-alt rounded w-2/3" />
      <div className="h-4 bg-surface-alt rounded w-1/2" />
    </div>
  )
}
