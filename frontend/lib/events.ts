'use client'

/**
 * One small event so every independently-mounted widget (sidebar badges, page
 * headers, job lists) refreshes the moment something changes, instead of
 * waiting for its own 15s poll.
 */
export const DATA_CHANGED = 'jobpilot:data-changed'

export function notifyDataChanged() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(DATA_CHANGED))
}

export function onDataChanged(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(DATA_CHANGED, handler)
  return () => window.removeEventListener(DATA_CHANGED, handler)
}
