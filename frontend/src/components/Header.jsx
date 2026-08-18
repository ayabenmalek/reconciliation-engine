export default function Header({ engineStatus, health }) {
  const isReady = engineStatus === 'ready'
  const isChecking = engineStatus === 'checking'

  const dotColor = isReady ? 'bg-success' : isChecking ? 'bg-muted' : 'bg-danger'
  const statusText = isReady ? 'Live' : isChecking ? 'Checking...' : 'Offline'

  return (
    <header className="sticky top-0 z-20 border-b border-edge bg-navy/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 px-6 py-4">
        {/* Left — identity */}
        <div className="flex items-center gap-3">
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-edge bg-surface text-xl"
            aria-hidden="true"
          >
            ⚖
          </span>
          <div className="leading-tight">
            <h1 className="text-lg font-semibold tracking-tight text-ink">Reconciliation Agent</h1>
            <p className="text-xs text-muted">GL Transaction Matching</p>
          </div>
        </div>

        {/* Right — status */}
        <div className="flex flex-wrap items-center gap-3">
          {!isReady && !isChecking && (
            <span className="text-xs font-medium text-danger">
              Backend offline — start the Colab notebook
            </span>
          )}

          <span
            className="flex items-center gap-2 rounded-full border border-edge bg-surface px-3 py-1"
            title={
              isReady
                ? `engine ${health?.engine_version ?? 'V1'} · ${health?.n_features ?? '?'} features · ${health?.device ?? '?'}${
                    health?.last_run ? ` · last run ${health.last_run}` : ''
                  }`
                : 'No response from the backend /health endpoint'
            }
          >
            <span
              className={`h-2 w-2 rounded-full ${dotColor} ${isReady ? 'animate-pulse-dot' : ''}`}
              aria-hidden="true"
            />
            <span className={`text-xs font-semibold ${isReady ? 'text-success' : isChecking ? 'text-muted' : 'text-danger'}`}>
              {statusText}
            </span>
          </span>
        </div>
      </div>
    </header>
  )
}
