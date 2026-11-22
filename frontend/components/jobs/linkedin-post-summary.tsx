'use client'

import { useMemo, useState } from 'react'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'

import { PostBody } from '@/components/jobs/post-body'
import type { Job } from '@/lib/types'
import { cn } from '@/lib/utils'

const LABELS = [
  'Required Skills',
  'Bonus Skills',
  'Hiring Process',
  'Employment Type',
  'Job Type',
  'Experience',
  'Compensation',
  'Workload',
  'Schedule',
  'Company',
  'Location',
  'Role',
  'Salary',
  'Skills',
]

const FIELD_RE = new RegExp(
  `(${LABELS.map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\s*:\\s*([^|•▪\\n]+)`,
  'gi',
)

type Fields = Record<string, string>

function clean(text: string): string {
  return (text || '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[ \t]+/g, ' ')
    .trim()
}

function fieldsOf(text: string): Fields {
  const fields: Fields = {}
  for (const match of text.matchAll(FIELD_RE)) {
    const key = match[1].toLowerCase()
    const value = match[2].replace(/\s+/g, ' ').trim()
    if (value && !fields[key]) fields[key] = value
  }
  return fields
}

function short(text: string, limit = 190): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (compact.length <= limit) return compact
  return `${compact.slice(0, limit).trimEnd()}…`
}

function firstLine(text: string): string {
  const beforeFields = text.split(/(?:Company|Role|Location|Job Type|Experience)\s*:/i)[0]
  const stripped = beforeFields
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return stripped.length > 16 ? stripped : ''
}

function Detail({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="truncate text-xs text-foreground/90" title={value}>
        {value}
      </dd>
    </div>
  )
}

export function LinkedInPostSummary({ job, text }: { job: Job; text: string }) {
  const [expanded, setExpanded] = useState(false)
  const cleaned = useMemo(() => clean(text), [text])
  const fields = useMemo(() => fieldsOf(cleaned), [cleaned])

  const company = fields['company'] || job.company || ''
  const location = fields['location'] || job.job_location || ''
  const type = fields['job type'] || fields['employment type'] || ''
  const experience = fields['experience'] || ''
  const workload = fields['workload'] || ''
  const pay = fields['compensation'] || fields['salary'] || ''
  const skills = (fields['required skills'] || fields['skills'] || '')
    .split(/[,;·]/)
    .map((skill) =>
      skill
        .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, ' ')
        .replace(/[^\p{L}\p{N}+#./ -]/gu, ' ')
        .replace(/\s+/g, ' ')
        .trim(),
    )
    .filter(Boolean)
    .slice(0, 5)
  const lead = firstLine(cleaned) || short(cleaned)

  const details = [
    { label: 'Company', value: company },
    { label: 'Location', value: location },
    { label: 'Type', value: type },
    { label: 'Experience', value: experience },
    { label: 'Workload', value: workload },
    { label: 'Pay', value: pay },
  ].filter((item) => item.value)

  return (
    <div className="mt-3 rounded-xl border border-border/70 bg-muted/20 px-3.5 py-3">
      {lead ? (
        <p className="line-clamp-2 text-sm leading-relaxed text-foreground/90">{lead}</p>
      ) : null}

      {details.length ? (
        <dl className={cn('mt-2.5 grid gap-x-4 gap-y-2', details.length > 2 ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2')}>
          {details.map((item) => (
            <Detail key={item.label} label={item.label} value={item.value} />
          ))}
        </dl>
      ) : null}

      {skills.length ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            Skills
          </span>
          {skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-foreground/80"
            >
              {skill}
            </span>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        {expanded ? <ChevronUpIcon className="size-3" /> : <ChevronDownIcon className="size-3" />}
        {expanded ? 'Hide original post' : 'Show original post'}
      </button>

      {expanded ? <PostBody text={cleaned} expanded /> : null}
    </div>
  )
}
