import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_URL, apiErrorMessage, getHealth, postReconcile, postReview } from './api.js'
import DownloadButtons from './components/DownloadButtons.jsx'
import Header from './components/Header.jsx'
import LLMReviewSection from './components/LLMReviewSection.jsx'
import MatchedGroupsTable from './components/MatchedGroupsTable.jsx'
import MetricsRow from './components/MetricsRow.jsx'
import UnmatchedTable from './components/UnmatchedTable.jsx'
import UploadSection from './components/UploadSection.jsx'

const HEALTH_INTERVAL_MS = 30_000

export default function App() {
  const [file, setFile] = useState(null)
  const [isRunning, setIsRunning] = useState(false)
  const [results, setResults] = useState(null)
  const [llmResults, setLlmResults] = useState(null)
  const [engineStatus, setEngineStatus] = useState('checking')
  const [runId, setRunId] = useState(null)

  const [health, setHealth] = useState(null)
  const [runError, setRunError] = useState(null)
  const [isReviewing, setIsReviewing] = useState(false)
  const [reviewError, setReviewError] = useState(null)

  // ── Health polling ────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    const check = async () => {
      try {
        const data = await getHealth()
        if (cancelled) return
        setHealth(data)
        setEngineStatus(data?.status === 'ready' ? 'ready' : 'offline')
      } catch {
        if (cancelled) return
        setHealth(null)
        setEngineStatus('offline')
      }
    }

    check()
    const id = setInterval(check, HEALTH_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // ── /reconcile ────────────────────────────────────────────────────────────
  const handleRun = useCallback(async () => {
    if (!file) return
    setIsRunning(true)
    setRunError(null)
    // A new run invalidates the previous run's LLM pass.
    setLlmResults(null)
    setReviewError(null)

    try {
      const data = await postReconcile(file)
      setResults(data)
      setRunId(data?.run_id ?? null)
    } catch (err) {
      // Keep the selected file so the user can simply retry.
      setRunError(apiErrorMessage(err, 'Reconciliation failed'))
    } finally {
      setIsRunning(false)
    }
  }, [file])

  // ── /review ───────────────────────────────────────────────────────────────
  const handleReview = useCallback(
    async ({ apiKey, model, baseUrl }) => {
      if (!runId) return
      setIsReviewing(true)
      setReviewError(null)
      try {
        const data = await postReview({ runId, apiKey, model, baseUrl })
        setLlmResults(data)
      } catch (err) {
        // Existing engine results stay on screen.
        setReviewError(apiErrorMessage(err, 'LLM review failed'))
      } finally {
        setIsReviewing(false)
      }
    },
    [runId],
  )

  // ── Derived views ─────────────────────────────────────────────────────────
  // Engine groups first, then LLM groups appended.
  const allGroups = useMemo(
    () => [...(results?.matched ?? []), ...(llmResults?.new_groups ?? [])],
    [results, llmResults],
  )

  // Drop the rows the LLM actually claimed, rather than trusting a count — this
  // keeps the table and the Unmatched metric in agreement no matter what.
  const recoveredRowIdx = useMemo(() => {
    const set = new Set()
    for (const group of llmResults?.new_groups ?? []) {
      for (const member of group.members ?? []) set.add(member.row_idx)
    }
    return set
  }, [llmResults])

  const unmatchedRows = useMemo(
    () => (results?.unmatched ?? []).filter((row) => !recoveredRowIdx.has(row.row_idx)),
    [results, recoveredRowIdx],
  )

  const recoveredCount = (results?.unmatched?.length ?? 0) - unmatchedRows.length
  const hasResults = Boolean(results)

  return (
    <div className="min-h-screen bg-navy">
      <Header engineStatus={engineStatus} health={health} />

      <main className="mx-auto flex max-w-[1600px] flex-col gap-6 px-6 py-6">
        <UploadSection
          file={file}
          onFileChange={setFile}
          onRun={handleRun}
          isRunning={isRunning}
          error={runError}
          elapsed={results?.elapsed_s}
        />

        {hasResults && (
          <>
            <MetricsRow summary={results.summary} unmatchedCount={unmatchedRows.length} />

            <MatchedGroupsTable groups={allGroups} />

            <UnmatchedTable rows={unmatchedRows} recoveredCount={recoveredCount} />

            <LLMReviewSection
              onReview={handleReview}
              isReviewing={isReviewing}
              llmResults={llmResults}
              error={reviewError}
              disabled={!runId}
            />

            <DownloadButtons runId={runId} hasLLMResults={Boolean(llmResults)} />
          </>
        )}

        <footer className="pb-4 text-center font-mono text-[11px] text-muted">
          API · {API_URL}
        </footer>
      </main>
    </div>
  )
}
