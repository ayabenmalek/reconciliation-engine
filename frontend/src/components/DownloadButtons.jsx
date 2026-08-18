import { useState } from 'react'
import { apiErrorMessage, downloadResults } from '../api.js'
import Spinner from './Spinner.jsx'

const BUTTONS = [
  { kind: 'matched', label: 'Download Matched CSV', color: '#3DBD7D' },
  { kind: 'unmatched', label: 'Download Unmatched CSV', color: '#E05555' },
  { kind: 'llm_matched', label: 'Download LLM Results', color: '#A78BFA', requiresLLM: true },
]

export default function DownloadButtons({ runId, hasLLMResults }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  const handle = async (kind) => {
    if (!runId) return
    setBusy(kind)
    setError(null)
    try {
      await downloadResults(runId, kind)
    } catch (err) {
      setError(apiErrorMessage(err, `Could not download ${kind}.csv`))
    } finally {
      setBusy(null)
    }
  }

  const visible = BUTTONS.filter((b) => !b.requiresLLM || hasLLMResults)

  return (
    <section className="animate-fade-in rounded-xl border border-edge bg-surface p-5">
      <h2 className="mb-3 text-sm font-semibold tracking-wide text-ink uppercase">Export</h2>

      <div className="flex flex-wrap gap-3">
        {visible.map(({ kind, label, color }) => {
          const disabled = !runId || busy !== null
          return (
            <button
              key={kind}
              onClick={() => handle(kind)}
              disabled={disabled}
              className={`flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition ${
                disabled ? 'cursor-not-allowed opacity-40' : 'hover:bg-surface-hover'
              }`}
              style={{ borderColor: `${color}59`, color }}
            >
              {busy === kind ? (
                <Spinner className="h-4 w-4" color={color} />
              ) : (
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v12m0 0 4-4m-4 4-4-4" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1" />
                </svg>
              )}
              {label}
            </button>
          )
        })}
      </div>

      {runId && (
        <p className="mt-3 font-mono text-[11px] text-muted">run_id: {runId}</p>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  )
}
