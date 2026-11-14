'use client'

import { useCallback, useEffect, useState } from 'react'
import { ScrollTextIcon } from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import type { Run } from '@/lib/types'
import { timeAgo } from '@/lib/utils'

const SUMMARY_LABELS: Record<string, string> = {
  posts_seen: 'seen',
  posts_new: 'new',
  duplicates: 'dupes',
  relevant: 'relevant',
  queued: 'queued',
  pending_approval: 'to review',
  rejected: 'rejected',
  feed_posts: 'from feed',
  queries: 'queries',
  attempted: 'attempted',
  replied: 'replied',
  dm_sent: 'DMs',
  failed: 'failed',
  deferred: 'deferred',
  stopped: 'stopped',
}

function summarise(stats: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(stats || {})) {
    if (key === 'errors' || key === 'keywords') continue
    const label = SUMMARY_LABELS[key]
    if (!label) continue
    if (value === 0 || value === '' || value === null || value === undefined) continue
    parts.push(`${label} ${value}`)
  }
  const errors = (stats?.errors as string[] | undefined) || []
  if (errors.length) parts.push(`${errors.length} error(s)`)
  return parts.join(' · ') || 'no changes'
}

export default function ActivityPage() {
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setRuns(await api.runs())
      setError('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [load])

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Activity"
        description="Every scan and every send batch, with what changed."
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load runs</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <ScrollTextIcon className="mx-auto mb-2 size-5 text-muted-foreground" />
          <p className="text-sm font-medium">No runs yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Every scan and every send batch appears here.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card px-4">
          {runs.map((run, index) => {
            const variant =
              run.status === 'completed'
                ? 'success'
                : run.status === 'running'
                  ? 'info'
                  : run.status === 'skipped'
                    ? 'outline'
                    : 'destructive'
            return (
              <div
                key={run.id}
                className={`flex items-start justify-between gap-4 py-3 ${
                  index < runs.length - 1 ? 'border-b border-border/60' : ''
                }`}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">#{run.id}</span>
                    <Badge variant={variant}>{run.status}</Badge>
                    <span className="text-[11px] text-muted-foreground">{run.kind}</span>
                    <span className="text-[11px] text-muted-foreground">
                      · {timeAgo(run.started_at)}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{summarise(run.stats)}</p>
                  {run.error ? (
                    <p className="mt-1 text-[11px] text-destructive">{run.error}</p>
                  ) : null}
                </div>
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {run.finished_at ? timeAgo(run.finished_at) : 'running'}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </main>
  )
}
