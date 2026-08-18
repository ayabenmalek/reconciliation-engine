import { formatVND, isCredit, memberAmount } from '../utils.js'

const COLUMNS = 'minmax(11rem,14rem) 5.5rem 9rem 9rem 7rem minmax(0,1.4fr) minmax(0,1fr)'

export default function UnmatchedTable({ rows, recoveredCount }) {
  return (
    <section className="animate-fade-in rounded-xl border border-edge bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-edge px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">
          Unmatched <span className="font-mono text-muted">({rows.length})</span>
        </h2>
        {recoveredCount > 0 && (
          <span className="rounded-full border border-success/40 bg-success/10 px-3 py-1 text-xs font-medium text-success">
            {recoveredCount} recovered by LLM review
          </span>
        )}
      </div>

      <div className="border-b border-danger/30 bg-danger/10 px-4 py-2.5">
        <p className="text-xs text-danger">
          ⚠ These transactions could not be matched and require manual auditor review
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-success">
          Every transaction was matched — nothing left for manual review.
        </p>
      ) : (
        <>
          <div
            className="grid gap-3 border-b border-edge px-3 py-2 text-[10px] font-semibold tracking-wider text-muted uppercase"
            style={{ gridTemplateColumns: COLUMNS }}
          >
            <span>SOGD ID</span>
            <span>Side</span>
            <span className="text-right">Amount</span>
            <span>Account</span>
            <span>Date</span>
            <span>Remarks</span>
            <span>Dien Giai</span>
          </div>

          <div className="max-h-[50vh] overflow-y-auto">
            {rows.map((row, i) => {
              const credit = isCredit(row)
              return (
                <div
                  key={`${row.row_idx}-${i}`}
                  className="grid items-center gap-3 border-b border-edge/60 px-3 py-2 text-xs transition last:border-b-0 hover:bg-surface-hover/60"
                  style={{ backgroundColor: i % 2 === 1 ? '#16294699' : 'transparent', gridTemplateColumns: COLUMNS }}
                >
                  <span className="truncate font-mono text-accent" title={row.sogd_id}>
                    {row.sogd_id || '—'}
                  </span>
                  <span
                    className="w-fit rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold"
                    style={{
                      color: credit ? '#3DBD7D' : '#E05555',
                      backgroundColor: credit ? '#3DBD7D1A' : '#E055551A',
                    }}
                  >
                    {credit ? 'CREDIT' : 'DEBIT'}
                  </span>
                  <span className="text-right font-mono text-ink">{formatVND(memberAmount(row))}</span>
                  <span className="truncate font-mono text-muted">{row.so_tai_khoan || '—'}</span>
                  <span className="font-mono text-muted">{row.ngaygd || '—'}</span>
                  <span className="truncate text-ink/80" title={row.cust_remarks}>
                    {row.cust_remarks || '—'}
                  </span>
                  <span className="truncate text-muted" title={row.dien_giai}>
                    {row.dien_giai || '—'}
                  </span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}
