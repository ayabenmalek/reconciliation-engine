import { useMemo, useState } from 'react'
import { MECHANISM_COLORS, TOPOLOGY_LABELS, TOPOLOGY_ORDER } from '../constants.js'
import {
  formatVND,
  isCredit,
  isLLMGroup,
  isLLMMechanism,
  justificationText,
  mechanismColor,
  mechanismKey,
  mechanismPillText,
  mechanismParts,
  memberAmount,
  topologyLabel,
  truncate,
} from '../utils.js'

// Shared column template so the header and every row stay aligned.
const COLUMNS = '2rem minmax(11rem,13rem) 4.5rem minmax(0,1fr) 9rem 9rem 5rem 8rem'

const CONFIDENCE_STYLES = {
  high: { color: '#3DBD7D', border: '#3DBD7D' },
  medium: { color: '#E8A230', border: '#E8A230' },
  low: { color: '#E05555', border: '#E05555' },
}

function Select({ label, value, onChange, options }) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-edge bg-navy px-2.5 py-1.5 text-xs text-ink outline-none transition focus:border-accent"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function MemberCard({ member }) {
  const credit = isCredit(member)
  return (
    <div className="rounded-md border border-edge bg-navy p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs text-accent break-all">{member.sogd_id || '—'}</span>
        <span
          className="rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold"
          style={{
            color: credit ? '#3DBD7D' : '#E05555',
            backgroundColor: credit ? '#3DBD7D1A' : '#E055551A',
          }}
        >
          {credit ? 'CREDIT' : 'DEBIT'}
        </span>
      </div>

      <p className="font-mono text-sm text-ink">{formatVND(memberAmount(member))}</p>

      <dl className="mt-2 space-y-1 text-[11px]">
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-muted">Account</dt>
          <dd className="font-mono text-muted">{member.so_tai_khoan || '—'}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-muted">Date</dt>
          <dd className="font-mono text-muted">{member.ngaygd || '—'}</dd>
        </div>
        {member.chi_nhanh && (
          <div className="flex gap-2">
            <dt className="w-20 shrink-0 text-muted">Branch</dt>
            <dd className="text-muted">{member.chi_nhanh}</dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-muted">Remarks</dt>
          <dd className="text-ink/80 break-words">
            {member.cust_remarks || '—'}
            {member.cust_remarks2 ? ` · ${member.cust_remarks2}` : ''}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 shrink-0 text-muted">Dien Giai</dt>
          <dd className="text-ink/80 break-words">{member.dien_giai || '—'}</dd>
        </div>
      </dl>
    </div>
  )
}

function GroupRow({ group, index, expanded, onToggle }) {
  const llm = isLLMGroup(group)
  const color = mechanismColor(group.mechanism)
  const justification = justificationText(group.mechanism)
  const extraLabels = mechanismParts(group.mechanism).length - 1
  const confidence = CONFIDENCE_STYLES[group.confidence] ?? null
  const gap = Number(group.gap ?? 0)
  const gapIsZero = Math.abs(gap) < 1e-9

  return (
    <div
      className="border-b border-edge/60 last:border-b-0"
      style={{
        backgroundColor: index % 2 === 1 ? '#16294699' : 'transparent',
        borderLeft: llm ? '3px solid #A78BFA' : '3px solid transparent',
      }}
    >
      {/* Summary row */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle()
          }
        }}
        className="grid cursor-pointer items-center gap-3 px-3 py-2.5 transition hover:bg-surface-hover/60"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        <svg
          className="h-4 w-4 text-muted transition-transform duration-300"
          style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
        </svg>

        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-xs text-accent" title={group.group_id}>
            {group.group_id}
          </span>
          {llm && (
            <span
              className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold"
              style={{ color: '#A78BFA', backgroundColor: '#A78BFA1F' }}
            >
              LLM
            </span>
          )}
        </div>

        <span className="rounded-full border border-edge bg-navy px-2 py-0.5 text-center font-mono text-[11px] text-muted">
          {topologyLabel(group.topology)}
        </span>

        {/* Mechanism + one-line justification */}
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span
              className="truncate rounded px-2 py-0.5 font-mono text-[11px] font-medium"
              style={{ color, backgroundColor: `${color}1F` }}
              title={group.mechanism}
            >
              {mechanismPillText(group.mechanism)}
            </span>
            {extraLabels > 0 && (
              <span className="shrink-0 rounded bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted">
                +{extraLabels}
              </span>
            )}
            {confidence && (
              <span
                className="shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-semibold capitalize"
                style={{ color: confidence.color, borderColor: `${confidence.border}66` }}
              >
                {group.confidence}
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-[11px] italic text-muted" title={justification}>
            {isLLMMechanism(group.mechanism) ? truncate(justification, 40) : justification}
          </p>
        </div>

        <span className="text-right font-mono text-xs text-ink">{formatVND(group.sum_credit)}</span>
        <span className="text-right font-mono text-xs text-ink">{formatVND(group.sum_debit)}</span>

        <span className="flex justify-center" title={group.is_balanced ? 'Balanced' : 'Unbalanced'}>
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: group.is_balanced ? '#3DBD7D' : '#E05555' }}
          />
          <span className="sr-only">{group.is_balanced ? 'balanced' : 'not balanced'}</span>
        </span>

        <span
          className="text-right font-mono text-xs"
          style={{ color: gapIsZero ? '#3DBD7D' : '#E05555' }}
        >
          {formatVND(gap)}
        </span>
      </div>

      {/* Expanded detail — 0fr→1fr keeps the height transition smooth */}
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-out"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-edge/60 bg-navy/40 px-6 py-4">
            {/* Justification, in full */}
            <div
              className="mb-4 flex gap-3 rounded-md border p-3"
              style={{ borderColor: `${color}59`, backgroundColor: `${color}14` }}
            >
              <span className="text-base leading-none" aria-hidden="true">
                💡
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold tracking-wider text-muted uppercase">
                  Justification
                </p>
                <p className="mt-1 text-sm leading-relaxed text-ink">{justification}</p>
                {mechanismParts(group.mechanism).length > 1 && (
                  <p className="mt-2 font-mono text-[11px] text-muted">
                    mechanism: {group.mechanism}
                  </p>
                )}
              </div>
            </div>

            <p className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">
              Members ({group.members?.length ?? 0})
            </p>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {(group.members ?? []).map((member, i) => (
                <MemberCard key={`${member.row_idx}-${i}`} member={member} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function MatchedGroupsTable({ groups }) {
  const [mechanismFilter, setMechanismFilter] = useState('all')
  const [topologyFilter, setTopologyFilter] = useState('all')
  const [balancedFilter, setBalancedFilter] = useState('all')
  const [expandedIds, setExpandedIds] = useState(() => new Set())

  const mechanismOptions = useMemo(() => {
    const present = new Set(groups.map((g) => mechanismKey(g.mechanism)))
    const ordered = Object.keys(MECHANISM_COLORS).filter((k) => present.has(k))
    return [{ value: 'all', label: 'All mechanisms' }, ...ordered.map((k) => ({ value: k, label: k }))]
  }, [groups])

  const filtered = useMemo(
    () =>
      groups.filter((g) => {
        if (mechanismFilter !== 'all' && mechanismKey(g.mechanism) !== mechanismFilter) return false
        if (topologyFilter !== 'all' && g.topology !== topologyFilter) return false
        if (balancedFilter === 'yes' && !g.is_balanced) return false
        if (balancedFilter === 'no' && g.is_balanced) return false
        return true
      }),
    [groups, mechanismFilter, topologyFilter, balancedFilter],
  )

  const toggle = (id) =>
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const allExpanded = filtered.length > 0 && filtered.every((g) => expandedIds.has(g.group_id))

  return (
    <section className="animate-fade-in rounded-xl border border-edge bg-surface">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 border-b border-edge px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">Matched groups</h2>

        <Select
          label="Mechanism"
          value={mechanismFilter}
          onChange={setMechanismFilter}
          options={mechanismOptions}
        />
        <Select
          label="Topology"
          value={topologyFilter}
          onChange={setTopologyFilter}
          options={[
            { value: 'all', label: 'All' },
            ...TOPOLOGY_ORDER.map((k) => ({ value: k, label: TOPOLOGY_LABELS[k] })),
          ]}
        />
        <Select
          label="Balanced"
          value={balancedFilter}
          onChange={setBalancedFilter}
          options={[
            { value: 'all', label: 'All' },
            { value: 'yes', label: 'Yes' },
            { value: 'no', label: 'No' },
          ]}
        />

        <span className="text-xs text-muted">
          Showing <span className="font-mono text-ink">{filtered.length}</span> of{' '}
          <span className="font-mono text-ink">{groups.length}</span> groups
        </span>

        <button
          onClick={() =>
            setExpandedIds(allExpanded ? new Set() : new Set(filtered.map((g) => g.group_id)))
          }
          disabled={filtered.length === 0}
          className="ml-auto rounded-md border border-edge px-3 py-1.5 text-xs text-muted transition hover:bg-surface-hover hover:text-ink disabled:opacity-40"
        >
          {allExpanded ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      {/* Column headings */}
      <div
        className="grid gap-3 border-b border-edge px-3 py-2 text-[10px] font-semibold tracking-wider text-muted uppercase"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        <span />
        <span>Group ID</span>
        <span className="text-center">Topology</span>
        <span>Mechanism</span>
        <span className="text-right">Credits</span>
        <span className="text-right">Debits</span>
        <span className="text-center">Bal.</span>
        <span className="text-right">Gap</span>
      </div>

      {/* Rows */}
      <div className="max-h-[70vh] overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted">
            No groups match the current filters.
          </p>
        ) : (
          filtered.map((group, i) => (
            <GroupRow
              key={group.group_id}
              group={group}
              index={i}
              expanded={expandedIds.has(group.group_id)}
              onToggle={() => toggle(group.group_id)}
            />
          ))
        )}
      </div>
    </section>
  )
}
