// ── Mechanism colours ───────────────────────────────────────────────────────
// Keyed by the canonical mechanism token the engine emits. `llm_tail` covers
// the `llm_tail:<free text>` form the /review endpoint returns.
export const MECHANISM_COLORS = {
  same_sogd: '#E8A230',
  refno_in_custremarks: '#3A8FA4',
  keywords: '#3DBD7D',
  one_one_sogd_prefix: '#F97316',
  llm_tail: '#A78BFA',
  balanced_only: '#8A9BB0',
}

export const FALLBACK_MECHANISM_COLOR = MECHANISM_COLORS.balanced_only

// Human-readable justification for each engine mechanism.
export const MECHANISM_LABELS = {
  same_sogd: 'Same SOGD base identifier — two legs of the same accounting event',
  refno_in_custremarks: 'Reference number found in partner remarks — explicit cross-reference',
  keywords: 'Shared structured identifier (12 or 15-digit code) in remarks',
  one_one_sogd_prefix: 'Sequential SOGD prefix — interbank or treasury settlement pair',
  balanced_only: 'Balanced by amount — no explicit textual link found',
  amount_indexed: 'Amount-indexed match — credits and debits sum to zero',
}

// ── Topology ────────────────────────────────────────────────────────────────
export const TOPOLOGY_LABELS = {
  '1_to_1': '1:1',
  '1_to_m': '1:m',
  'm_to_1': 'm:1',
  'm_to_m': 'm:m',
}

export const TOPOLOGY_ORDER = ['1_to_1', '1_to_m', 'm_to_1', 'm_to_m']

// ── LLM review ──────────────────────────────────────────────────────────────
export const LLM_MODELS = ['qwen/qwen3-8b:free']

export const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

// Rotating status messages shown while /reconcile is in flight.
export const RUN_MESSAGES = [
  'Classifying transaction remarks...',
  'Generating candidate pairs...',
  'Scoring with Fellegi-Sunter...',
  'Resolving balanced groups...',
  'Finalising results...',
]

export const LLM_PREFIX = 'llm_tail:'
export const LLM_GROUP_PREFIX = 'LLM_'
