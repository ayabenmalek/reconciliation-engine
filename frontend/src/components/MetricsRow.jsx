import { TOPOLOGY_LABELS, TOPOLOGY_ORDER } from '../constants.js'
import { formatPercent } from '../utils.js'

function MetricCard({ label, value, accent, hint }) {
  return (
    <div
      className="rounded-lg border border-edge bg-surface p-4 transition hover:bg-surface-hover"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <p className="text-[11px] font-semibold tracking-wider text-muted uppercase">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold text-ink">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-muted">{hint}</p>}
    </div>
  )
}

export default function MetricsRow({ summary, unmatchedCount }) {
  if (!summary) return null

  const topology = summary.topology ?? {}
  // Keep the four known topologies in a stable order, then anything unexpected.
  const topologyKeys = [
    ...TOPOLOGY_ORDER.filter((k) => k in topology),
    ...Object.keys(topology).filter((k) => !TOPOLOGY_ORDER.includes(k)),
  ]

  return (
    <section className="animate-fade-in">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Balance rate"
          value={formatPercent(summary.balance_rate)}
          accent="#E8A230"
          hint="Groups closing to zero"
        />
        <MetricCard
          label="Coverage"
          value={formatPercent(summary.coverage)}
          accent="#3A8FA4"
          hint={`${summary.n_transactions ?? '—'} transactions · ${summary.n_groups ?? '—'} groups`}
        />
        <MetricCard
          label="Balanced coverage"
          value={formatPercent(summary.balanced_coverage)}
          accent="#3DBD7D"
          hint="Rows inside balanced groups"
        />
        <MetricCard
          label="Unmatched"
          value={unmatchedCount ?? summary.n_unmatched ?? 0}
          accent="#E05555"
          hint="Require manual review"
        />
      </div>

      {/* Topology breakdown — rendered once for the run rather than repeated
          inside each card, where it would be identical four times over. */}
      {topologyKeys.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold tracking-wider text-muted uppercase">Topology</span>
          {topologyKeys.map((key) => (
            <span
              key={key}
              className="rounded-full border border-edge bg-surface px-2.5 py-1 font-mono text-[11px] text-muted"
            >
              {TOPOLOGY_LABELS[key] ?? key} = <span className="text-ink">{topology[key]}</span>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}
