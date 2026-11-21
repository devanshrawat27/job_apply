'use client'

import { useCallback, useEffect, useState } from 'react'
import { Loader2Icon, SearchIcon } from 'lucide-react'

import { JobCard } from '@/components/jobs/job-card'
import { PlatformSwitch, type Platform } from '@/components/jobs/platform-switch'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import { onDataChanged } from '@/lib/events'
import type { Job } from '@/lib/types'

const FILTERS = [
  { key: 'pending_approval', label: 'Needs approval' },
  { key: 'queued', label: 'Queued' },
  { key: 'sent', label: 'Sent' },
  { key: 'failed', label: 'Failed' },
  { key: 'rejected', label: 'Skipped' },
  { key: 'all', label: 'Everything' },
]

function friendlyError(message: string): string {
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(message)) {
    return 'The API is not reachable right now. It restarts automatically and this list retries every 20 seconds - no action needed.'
  }
  return message
}

const EMPTY: Record<string, { title: string; description: string }> = {
  pending_approval: {
    title: 'Nothing needs your approval',
    description:
      'The agent is handling posts on its own. It only stops here when it is not sure enough to send.',
  },
  queued: {
    title: 'Nothing queued right now',
    description:
      'Strong matches are queued here and sent automatically after the cool-down, one at a time.',
  },
  sent: {
    title: 'Nothing sent yet',
    description: 'Replies, DMs and applications the agent delivered will show up here.',
  },
  failed: {
    title: 'No failed posts',
    description: 'Anything that did not go through will appear here with the exact reason.',
  },
  rejected: {
    title: 'Nothing skipped',
    description: 'Posts the agent rejected as not a fit are listed here, with the reason.',
  },
  all: {
    title: 'No posts yet',
    description:
      'The agent scans X and LinkedIn automatically. Fresh jobs appear here within a few minutes.',
  },
}

const PLATFORM_KEY = 'jobpilot.platform'

type JobStats = Awaited<ReturnType<typeof api.jobStats>>

export function JobList({
  mode,
  refreshKey,
  onChanged,
}: {
  mode: 'all' | 'review' | 'links'
  refreshKey: number
  onChanged: () => Promise<void>
}) {
  const [filter, setFilter] = useState('pending_approval')
  const [source, setSource] = useState<Platform>('all')
  const [stats, setStats] = useState<JobStats | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // The platform choice follows the person across Found jobs, Apply links and
  // Approvals instead of resetting on every page.
  useEffect(() => {
    const saved = window.localStorage.getItem(PLATFORM_KEY)
    if (saved === 'x' || saved === 'linkedin' || saved === 'all') setSource(saved)
  }, [])

  function changePlatform(next: Platform) {
    setSource(next)
    window.localStorage.setItem(PLATFORM_KEY, next)
  }

  const load = useCallback(async () => {
    try {
      setError('')
      const sourceFilter = source === 'all' ? undefined : source
      const [rows, totals] = await Promise.all([
        mode === 'links'
          ? api.jobs({
              has_link: true,
              open_only: true,
              sort: 'best',
              source: sourceFilter,
            })
          : api.jobs({ status: filter, source: sourceFilter }),
        api.jobStats(),
      ])
      setJobs(rows)
      setStats(totals)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filter, mode, source])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load, refreshKey])

  // Keep the list in step with the background agent and other tabs.
  useEffect(() => {
    const timer = window.setInterval(() => void load(), 20_000)
    const off = onDataChanged(() => void load())
    const onFocus = () => void load()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.clearInterval(timer)
      off()
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [load])

  async function refresh() {
    await load()
    await onChanged()
  }

  const baseCounts =
    mode === 'links'
      ? stats?.apply_links_by_source
      : mode === 'review'
        ? stats?.pending_by_source
        : filter === 'all'
          ? stats?.by_source
          : stats?.by_status_source?.[filter]
  const counts: Record<Platform, number> = {
    x: baseCounts?.x ?? 0,
    linkedin: baseCounts?.linkedin ?? 0,
    all: (baseCounts?.x ?? 0) + (baseCounts?.linkedin ?? 0),
  }

  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load posts</AlertTitle>
          <AlertDescription>{friendlyError(error)}</AlertDescription>
        </Alert>
      ) : null}

      <PlatformSwitch value={source} onChange={changePlatform} counts={counts} />

      {mode === 'all' ? (
        <div className="inline-flex flex-wrap gap-1 rounded-xl border border-border bg-muted/30 p-1">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={filter === item.key}
              onClick={() => setFilter(item.key)}
              className={
                filter === item.key
                  ? 'rounded-lg bg-background px-3 py-1.5 text-xs font-medium text-foreground shadow-sm'
                  : 'rounded-lg px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground'
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}

      {loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="flex flex-col items-center rounded-xl border border-dashed border-border px-6 py-14 text-center">
          <span className="mb-3 grid size-11 place-items-center rounded-full bg-muted text-muted-foreground">
            <SearchIcon className="size-5" />
          </span>
          <p className="text-sm font-medium">
            {mode === 'review'
              ? EMPTY.pending_approval.title
              : mode === 'links'
                ? 'No direct apply links right now'
                : (EMPTY[filter] ?? EMPTY.all).title}
          </p>
          <p className="mt-1 max-w-md text-xs text-muted-foreground">
            {mode === 'review'
              ? EMPTY.pending_approval.description
              : mode === 'links'
                ? 'Posts with an application link show up here so you can apply yourself in one click.'
                : (EMPTY[filter] ?? EMPTY.all).description}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              review={mode === 'review'}
              applyMode={mode === 'links'}
              onChange={refresh}
            />
          ))}
        </div>
      )}

      {loading && jobs.length > 0 ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2Icon className="size-3 animate-spin" />
          Refreshing…
        </div>
      ) : null}
    </div>
  )
}
