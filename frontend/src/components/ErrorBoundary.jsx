import { Component } from 'react'

/**
 * Last line of defence: a render error in any panel must not blank the page.
 * API failures are handled inline by the components themselves — this only
 * catches genuine render/runtime bugs.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Unhandled UI error:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="flex min-h-screen items-center justify-center bg-navy p-8">
        <div className="max-w-lg rounded-lg border border-danger/40 bg-surface p-6">
          <h1 className="mb-2 text-lg font-semibold text-danger">Something broke in the interface</h1>
          <p className="mb-4 text-sm text-muted">
            The reconciliation results are unaffected — reload the page to continue.
          </p>
          <pre className="mb-4 max-h-40 overflow-auto rounded bg-navy p-3 font-mono text-xs text-muted">
            {String(this.state.error?.message ?? this.state.error)}
          </pre>
          <button
            onClick={() => window.location.reload()}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-navy transition hover:brightness-110"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
