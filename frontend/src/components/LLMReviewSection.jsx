import { useState } from 'react'
import { LLM_MODELS, OPENROUTER_BASE_URL } from '../constants.js'
import Spinner from './Spinner.jsx'

export default function LLMReviewSection({ onReview, isReviewing, llmResults, error, disabled }) {
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(LLM_MODELS[0])

  const canRun = apiKey.trim().length > 0 && !isReviewing && !disabled

  return (
    <section className="animate-fade-in rounded-xl border border-edge bg-surface p-5">
      <div className="mb-1 flex items-center gap-2">
        <span className="text-base leading-none" aria-hidden="true">
          🤖
        </span>
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">
          Review unmatched transactions with LLM
        </h2>
      </div>
      <p className="mb-4 text-xs text-muted">
        Sends the unmatched tail to an OpenRouter model for a second pass. Optional — engine results
        above are unaffected.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[18rem] flex-1 flex-col gap-1.5">
          <span className="text-[11px] font-semibold tracking-wider text-muted uppercase">
            OpenRouter API key
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-or-..."
            autoComplete="off"
            className="rounded-md border border-edge bg-navy px-3 py-2 font-mono text-sm text-ink placeholder:text-muted/60 outline-none transition focus:border-accent"
          />
        </label>

        <label className="flex min-w-[16rem] flex-col gap-1.5">
          <span className="text-[11px] font-semibold tracking-wider text-muted uppercase">Model</span>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="rounded-md border border-edge bg-navy px-3 py-2 text-sm text-ink outline-none transition focus:border-accent"
          >
            {LLM_MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        <button
          onClick={() => onReview({ apiKey: apiKey.trim(), model, baseUrl: OPENROUTER_BASE_URL })}
          disabled={!canRun}
          className={`rounded-md px-5 py-2.5 text-sm font-semibold transition ${
            canRun
              ? 'text-navy hover:brightness-110 active:brightness-95'
              : 'cursor-not-allowed bg-surface-hover text-muted'
          }`}
          style={canRun ? { backgroundColor: '#A78BFA' } : undefined}
        >
          {isReviewing ? 'Reviewing...' : 'Run LLM review'}
        </button>

        {isReviewing && (
          <span className="flex items-center gap-2 text-sm text-muted">
            <Spinner />
            Analysing unmatched transactions...
          </span>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {llmResults && (
        <div
          className="mt-4 rounded-lg border p-4"
          style={{ borderColor: '#A78BFA59', backgroundColor: '#A78BFA14' }}
        >
          <p className="text-sm text-ink">
            LLM found <span className="font-mono font-semibold" style={{ color: '#A78BFA' }}>
              {llmResults.n_new_groups ?? 0}
            </span>{' '}
            new groups — recovered{' '}
            <span className="font-mono font-semibold text-success">{llmResults.n_recovered ?? 0}</span>{' '}
            transactions —{' '}
            <span className="font-mono font-semibold text-danger">
              {llmResults.still_unmatched ?? 0}
            </span>{' '}
            still unmatched
          </p>
          <p className="mt-1 text-[11px] text-muted">
            New groups are listed in the matched table above with a purple border.
          </p>

          {llmResults.errors?.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-edge pt-3">
              {llmResults.errors.map((e, i) => (
                <li key={i} className="text-xs text-danger">
                  · {typeof e === 'string' ? e : JSON.stringify(e)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
