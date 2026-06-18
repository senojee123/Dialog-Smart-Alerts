import { formatDistanceToNow, format } from 'date-fns'

export function relativeTime(dateStr) {
  if (!dateStr) return '—'
  try {
    return formatDistanceToNow(new Date(dateStr), { addSuffix: true })
  } catch {
    return dateStr
  }
}

export function absoluteTime(dateStr) {
  if (!dateStr) return '—'
  try {
    return format(new Date(dateStr), 'dd MMM yyyy HH:mm:ss')
  } catch {
    return dateStr
  }
}

export function formatDistance(metres) {
  if (metres == null) return '—'
  if (metres < 1000) return `${metres}m`
  return `${(metres / 1000).toFixed(1)}km`
}

export function deliveryLabel(delivered, total) {
  if (total === 0) return '—'
  return `${delivered}/${total}`
}
