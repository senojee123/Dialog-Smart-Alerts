import { absoluteTime } from '../../lib/format.js'

export default function Timeline({ entries = [] }) {
  return (
    <ol className="relative border-l-2 border-line ml-2 space-y-4">
      {entries.map((e, i) => (
        <li key={i} className="ml-4">
          <span className="absolute -left-1.5 mt-1 w-3 h-3 rounded-full bg-line border-2 border-white" />
          <time className="text-xs text-ink-muted">{absoluteTime(e.ts)}</time>
          <p className="text-sm text-ink mt-0.5">{e.event}</p>
        </li>
      ))}
    </ol>
  )
}
