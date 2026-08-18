import { useEffect, useRef, useState } from 'react'
import { RUN_MESSAGES } from '../constants.js'
import Spinner from './Spinner.jsx'

export default function UploadSection({ file, onFileChange, onRun, isRunning, error, elapsed }) {
  const [dragging, setDragging] = useState(false)
  const [messageIdx, setMessageIdx] = useState(0)
  const inputRef = useRef(null)

  // Rotate the status line every 3s while the request is in flight.
  useEffect(() => {
    if (!isRunning) {
      setMessageIdx(0)
      return
    }
    const id = setInterval(() => {
      setMessageIdx((i) => (i + 1) % RUN_MESSAGES.length)
    }, 3000)
    return () => clearInterval(id)
  }, [isRunning])

  const pickFile = (candidate) => {
    if (candidate) onFileChange(candidate)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    if (isRunning) return
    pickFile(e.dataTransfer.files?.[0])
  }

  return (
    <section className="rounded-xl border border-edge bg-surface p-6">
      <h2 className="mb-1 text-sm font-semibold tracking-wide text-ink uppercase">Transaction file</h2>
      <p className="mb-4 text-xs text-muted">
        Upload a GL export as CSV. The engine blocks candidates by account and posting date.
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          if (!isRunning) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !isRunning && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !isRunning) {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition ${
          dragging
            ? 'border-accent bg-surface-hover'
            : 'border-edge hover:border-accent/60 hover:bg-surface-hover/40'
        } ${isRunning ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => {
            pickFile(e.target.files?.[0])
            // Allow re-selecting the same filename after a failed run.
            e.target.value = ''
          }}
        />

        <svg className="mb-3 h-8 w-8 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0L8 8m4-4 4 4" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>

        {file ? (
          <>
            <p className="font-mono text-sm text-accent">{file.name}</p>
            <p className="mt-1 text-xs text-muted">
              {(file.size / 1024).toFixed(1)} KB · click or drop to replace
            </p>
          </>
        ) : (
          <>
            <p className="text-sm text-ink">Drop a CSV here, or click to browse</p>
            <p className="mt-1 text-xs text-muted">Single file · multipart upload to /reconcile</p>
          </>
        )}
      </div>

      {/* Action row */}
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          onClick={onRun}
          disabled={!file || isRunning}
          className={`rounded-md px-5 py-2.5 text-sm font-semibold transition ${
            !file || isRunning
              ? 'cursor-not-allowed bg-surface-hover text-muted'
              : 'bg-accent text-navy hover:brightness-110 active:brightness-95'
          }`}
        >
          {isRunning ? 'Running...' : 'Run reconciliation'}
        </button>

        {isRunning && (
          <span className="flex items-center gap-2 text-sm text-muted">
            <Spinner />
            <span key={messageIdx} className="animate-fade-in">
              {RUN_MESSAGES[messageIdx]}
            </span>
          </span>
        )}

        {!isRunning && elapsed != null && (
          <span className="text-sm text-success">
            Completed in <span className="font-mono">{Number(elapsed).toFixed(1)}s</span>
          </span>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  )
}
