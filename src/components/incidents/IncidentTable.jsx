import { useMemo, useState } from 'react'
import { ChevronDown, Eye, EyeOff } from 'lucide-react'
import IncidentRow from './IncidentRow.jsx'
import { SkeletonRow } from '../common/Skeleton.jsx'
import { sevOrder } from '../../lib/severity.js'

const COLS = ['Severity', 'Incident', 'Time', 'Area / Location', 'Object', 'Conf.', 'Notify', 'Hardware', 'State']

const SEVERITIES = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const STATUSES   = ['ALL', 'ACTIVE', 'OPERATOR_REVIEW', 'RESOLVED', 'CLOSED']

export default function IncidentTable({ incidents, loading, selectedId, onSelect, mapOpen, onToggleMap }) {
  const [sevFilter,    setSevFilter]    = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')

  const filtered = useMemo(() => {
    let list = incidents
    if (sevFilter    !== 'ALL') list = list.filter(i => i.severity === sevFilter)
    if (statusFilter !== 'ALL') list = list.filter(i => i.status   === statusFilter)
    return [...list].sort((a, b) => {
      if (a.severity === 'CRITICAL' && b.severity !== 'CRITICAL') return -1
      if (b.severity === 'CRITICAL' && a.severity !== 'CRITICAL') return 1
      const so = sevOrder(a.severity) - sevOrder(b.severity)
      if (so !== 0) return so
      return new Date(b.opened_at) - new Date(a.opened_at)
    })
  }, [incidents, sevFilter, statusFilter])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Filters */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-line bg-surface shrink-0 flex-wrap">
        <FilterSelect label="Severity" value={sevFilter} onChange={setSevFilter} options={SEVERITIES} />
        <FilterSelect label="Status"   value={statusFilter} onChange={setStatusFilter} options={STATUSES} />
        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-ink-muted">{filtered.length} incidents</span>
          {onToggleMap && (
            <button
              onClick={onToggleMap}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium border border-line rounded bg-surface-alt hover:bg-line text-ink transition-colors"
              title={mapOpen ? "Hide Map" : "Show Map"}
            >
              {mapOpen ? <EyeOff size={14} /> : <Eye size={14} />}
              <span>{mapOpen ? "Hide Map" : "Show Map"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-auto flex-1">
        <table className="w-full min-w-[780px] border-collapse">
          <thead className="sticky top-0 bg-surface-alt z-10">
            <tr>
              {COLS.map(c => (
                <th key={c} className="px-3 py-2.5 text-left text-xs font-semibold text-ink-muted uppercase tracking-wide whitespace-nowrap border-b border-line">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} cols={9} />)
              : filtered.length === 0
              ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-ink-muted text-sm">
                    No active incidents
                  </td>
                </tr>
              )
              : filtered.map(inc => (
                <IncidentRow
                  key={inc.incident_id}
                  incident={inc}
                  selected={inc.incident_id === selectedId}
                  onClick={() => onSelect(inc)}
                />
              ))
            }
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FilterSelect({ label, value, onChange, options }) {
  return (
    <div className="relative flex items-center">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="appearance-none pl-3 pr-7 py-1.5 text-xs border border-line rounded bg-white text-ink focus:outline-none focus:ring-1 focus:ring-brand cursor-pointer"
      >
        {options.map(o => <option key={o} value={o}>{o === 'ALL' ? `${label}: All` : o.replace(/_/g, ' ')}</option>)}
      </select>
      <ChevronDown size={12} className="absolute right-2 text-ink-muted pointer-events-none" />
    </div>
  )
}
