import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatLabel(value: string): string {
  const text = (value || '').replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.max(0, Date.now() - then)
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function formatExperience(months: number): string {
  const total = Math.max(0, Math.floor(months || 0))
  const years = Math.floor(total / 12)
  const rest = total % 12
  const parts: string[] = []
  if (years) parts.push(`${years} yr${years === 1 ? '' : 's'}`)
  if (rest) parts.push(`${rest} mo`)
  return parts.join(' ')
}

/** Tidy a raw tweet for reading: repair wrapped links, drop hashtags. */
export function cleanPostText(text: string): string {
  let out = (text || '').replace(/\r\n/g, '\n')
  // X wraps long links: "https://\nlinks.example.com/x"
  out = out.replace(/https?:\/\/[ \t]*\n[ \t]*/g, 'https://')
  // Hashtags are decorative noise in a job post.
  out = out.replace(/(^|\s)#[\w_]+/g, ' ')
  out = out.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n')
  return out.trim()
}
