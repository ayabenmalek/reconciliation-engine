import {
  FALLBACK_MECHANISM_COLOR,
  LLM_GROUP_PREFIX,
  LLM_PREFIX,
  MECHANISM_COLORS,
  MECHANISM_LABELS,
  TOPOLOGY_LABELS,
} from './constants.js'

const vndFormatter = new Intl.NumberFormat('vi-VN')

/** 15895142 → "15.895.142" */
export const formatVND = (n) => {
  const value = Number(n)
  return Number.isFinite(value) ? vndFormatter.format(value) : '—'
}

export const topologyLabel = (t) => TOPOLOGY_LABELS[t] ?? t ?? '—'

export const isLLMGroup = (group) => Boolean(group?.group_id?.startsWith(LLM_GROUP_PREFIX))

export const isLLMMechanism = (mechanism) => Boolean(mechanism?.startsWith(LLM_PREFIX))

/**
 * The engine emits multi-label mechanisms joined with "|" (e.g.
 * "same_sogd|keywords"); the LLM emits "llm_tail:<free text>". Reduce either
 * to the single canonical token that drives colour and filtering.
 */
export function mechanismKey(mechanism) {
  if (!mechanism) return 'balanced_only'
  if (isLLMMechanism(mechanism)) return 'llm_tail'
  const primary = mechanism.split('|')[0].trim()
  return primary in MECHANISM_COLORS ? primary : 'balanced_only'
}

/** Every recognised label on a multi-label engine mechanism. */
export function mechanismParts(mechanism) {
  if (!mechanism || isLLMMechanism(mechanism)) return []
  return mechanism
    .split('|')
    .map((p) => p.trim())
    .filter(Boolean)
}

export const mechanismColor = (mechanism) =>
  MECHANISM_COLORS[mechanismKey(mechanism)] ?? FALLBACK_MECHANISM_COLOR

/** Short text for the pill itself. */
export function mechanismPillText(mechanism) {
  if (isLLMMechanism(mechanism)) return 'llm_tail'
  const parts = mechanismParts(mechanism)
  return parts[0] || 'balanced_only'
}

/**
 * Human-readable explanation of why a group was matched.
 * For LLM groups this is the model's own reasoning, which is the single most
 * useful field on the row — callers must not truncate it in detail views.
 */
export function justificationText(mechanism) {
  if (isLLMMechanism(mechanism)) {
    return mechanism.slice(LLM_PREFIX.length).trim() || 'Matched by LLM review.'
  }
  const parts = mechanismParts(mechanism)
  const described = parts.map((p) => MECHANISM_LABELS[p]).filter(Boolean)
  if (described.length) return described.join(' · ')
  return MECHANISM_LABELS.balanced_only
}

export function truncate(text, max = 40) {
  if (typeof text !== 'string') return ''
  return text.length > max ? `${text.slice(0, max).trimEnd()}…` : text
}

export const formatPercent = (v, digits = 1) =>
  Number.isFinite(Number(v)) ? `${(Number(v) * 100).toFixed(digits)}%` : '—'

/** true when the row is a credit leg. */
export const isCredit = (member) => Number(member?.ghi_co) > 0

export const memberAmount = (member) =>
  isCredit(member) ? Number(member?.ghi_co) : Number(member?.ghi_no)
