import axios from 'axios'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ngrok's free tier serves an HTML interstitial to anything that looks like a
// plain browser navigation, which turns JSON responses into unparseable HTML.
// This header opts every request out of it. Harmless against a local backend.
const client = axios.create({
  baseURL: API_URL,
  headers: { 'ngrok-skip-browser-warning': 'true' },
})

/** Pull a readable message out of an axios error (FastAPI uses `detail`). */
export function apiErrorMessage(err, fallback = 'Request failed') {
  if (err?.code === 'ECONNABORTED') return 'Request timed out — the backend took too long to respond.'
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d?.msg ?? JSON.stringify(d)).join('; ')
  }
  if (err?.response?.status) {
    return `${fallback} (HTTP ${err.response.status})`
  }
  if (err?.message === 'Network Error') {
    return `Cannot reach the backend at ${API_URL} — check the ngrok URL in .env and that the Colab notebook is running.`
  }
  return err?.message || fallback
}

export async function getHealth({ timeout = 8000 } = {}) {
  const { data } = await client.get('/health', { timeout })
  return data
}

export async function postReconcile(file) {
  const form = new FormData()
  form.append('file', file)
  // Content-Type is deliberately left unset so the browser adds the multipart
  // boundary itself.
  const { data } = await client.post('/reconcile', form)
  return data
}

export async function postReview({ runId, apiKey, model, baseUrl }) {
  const { data } = await client.post('/review', {
    run_id: runId,
    api_key: apiKey,
    model,
    base_url: baseUrl,
  })
  return data
}

/**
 * Fetch a results CSV and hand it to the browser as a download.
 * `kind` is one of: matched | unmatched | llm_matched
 */
export async function downloadResults(runId, kind) {
  const res = await client.get(`/results/${runId}/download/${kind}`, {
    responseType: 'blob',
  })

  // Prefer the server's filename when it sends one.
  const disposition = res.headers?.['content-disposition'] ?? ''
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
  const filename = match ? decodeURIComponent(match[1]) : `${kind}_${runId.slice(0, 8)}.csv`

  const href = URL.createObjectURL(res.data)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoke on the next tick so Firefox has time to start the download.
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
