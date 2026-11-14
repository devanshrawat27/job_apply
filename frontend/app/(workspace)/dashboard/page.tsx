'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  ArrowRightIcon,
  AtSignIcon,
  ClipboardCheckIcon,
  ClockIcon,
  Loader2Icon,
  MessageSquareIcon,
  PlayIcon,
  RadarIcon,
  SearchIcon,
  SendIcon,
  SparklesIcon,
} from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator, Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import type { Insight, WatcherReport } from '@/lib/types'
import { useWorkspace } from '@/lib/use-workspace'
import { cn, timeAgo } from '@/lib/utils'

export default function DashboardPage() {
  const { profile, settings, account, dashboard, loading, error } = useWorkspace()

  const usage = dashboard?.usage
  const pending = dashboard?.pending_approvals ?? 0

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Dashboard"
        description="Your job outreach at a glance."
        actions={
          <>
            <Badge variant="outline" className="gap-1.5">
              <span
                className={cn(
                  'size-1.5 rounded-full',
                  account ? 'bg-emerald-500' : 'bg-muted-foreground',
                )}
              />
              {account ? `@${account.username}` : 'No account'}
            </Badge>
            <Badge variant={dashboard?.enabled ? 'success' : 'warning'}>
              {dashboard?.enabled ? 'Agent running' : 'Agent paused'}
            </Badge>
          </>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Backend not reachable</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!loading && !profile?.onboarding_completed ? (
        <Alert>
          <RadarIcon className="size-4" />
          <AlertTitle>Finish setting up</AlertTitle>
          <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>Add your resume and connect the X account the agent should use.</span>
            <Link href="/onboarding" className={cn(buttonVariants({ size: 'sm' }))}>
              Resume setup
              <ArrowRightIcon className="size-4" />
            </Link>
          </AlertDescription>
        </Alert>
      ) : null}

      {/* command center */}
      <section className="rounded-2xl border border-border bg-gradient-to-br from-card via-card to-muted/40 p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              {profile?.full_name ? `Hi, ${profile.full_name.split(' ')[0]}` : 'Welcome'}
            </h1>
            <p className="text-sm text-muted-foreground">
              {profile?.job_title
                ? `Hunting ${profile.job_title} roles on X.`
                : 'Tell the agent which role to hunt for.'}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-2.5 py-1">
              <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
              Automatic — scans every {settings?.scan_interval_minutes ?? 30} min
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-2.5 py-1">
              <span className="size-1.5 animate-pulse rounded-full bg-sky-500" />
              Sends queued posts when the cool-down allows
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            icon={ClipboardCheckIcon}
            label="Waiting for you"
            value={loading ? '—' : pending}
            hint="posts the agent was unsure about"
          />
          <Metric
            icon={MessageSquareIcon}
            label="Replies today"
            value={loading ? '—' : `${usage?.replies_today ?? 0}/${usage?.daily_reply_cap ?? 0}`}
            hint="daily cap"
          />
          <Metric
            icon={SendIcon}
            label="DMs today"
            value={loading ? '—' : `${usage?.dms_today ?? 0}/${usage?.daily_dm_cap ?? 0}`}
            hint="daily cap"
          />
          <Metric
            icon={ClockIcon}
            label="Last scan"
            value={loading ? '—' : timeAgo(dashboard?.agent.last_scan ?? null)}
            hint={`every ${settings?.scan_interval_minutes ?? '—'} min`}
          />
        </div>

        {dashboard?.last_run ? (
          <div className="mt-4 rounded-xl border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Last {dashboard.last_run.kind}</span>
            {' · '}
            {dashboard.last_run.status}
            {' · '}
            {describeRun(dashboard.last_run.stats)}
          </div>
        ) : null}

        <Separator className="my-5" />

        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">This run loop</h2>
          <Badge variant="secondary">
            {usage?.in_quiet_hours ? 'quiet hours' : 'active window'}
          </Badge>
        </div>

        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <LoopStep
            icon={SearchIcon}
            title="Scan X"
            detail={`Every ${settings?.scan_interval_minutes ?? 30} min · posts newer than ${
              settings?.lookback_hours ?? 36
            }h`}
          />
          <LoopStep
            icon={ClipboardCheckIcon}
            title="Draft & decide"
            detail={`Relevance ≥ ${settings?.relevance_threshold ?? 65} · auto-send ≥ ${Math.round(
              (settings?.auto_send_confidence ?? 0.8) * 100,
            )}%`}
          />
          <LoopStep
            icon={SendIcon}
            title="Reply + DM"
            detail={`${settings?.use_public_reply ? 'public reply' : 'no reply'} · ${
              settings?.send_dms ? 'DM' : 'no DM'
            }`}
          />
        </div>

        <Link
          href="/approvals"
          className={cn(buttonVariants({ size: 'lg', variant: pending > 0 ? 'default' : 'outline' }), 'mt-4 w-full')}
        >
          <ClipboardCheckIcon className="size-4" />
          {pending > 0 ? `Review ${pending} draft${pending > 1 ? 's' : ''}` : 'Open approvals'}
        </Link>
      </section>

      {/* quick cards */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Card className="transition-colors hover:border-foreground/20">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <AtSignIcon className="size-4" />
              X account
            </CardTitle>
            <CardDescription>Where the agent replies and DMs from.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {loading ? '…' : account ? `@${account.username} · ${account.status}` : 'Not connected'}
            </span>
            <Link href="/settings" className="text-xs font-medium hover:underline">
              Manage
            </Link>
          </CardContent>
        </Card>

        <Card className="transition-colors hover:border-foreground/20">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <PlayIcon className="size-4" />
              Agent
            </CardTitle>
            <CardDescription>Pause, caps and approval policy.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {loading
                ? '…'
                : dashboard?.enabled
                  ? 'Scheduled scanning is on'
                  : 'Paused — run manually'}
            </span>
            <Link href="/settings" className="text-xs font-medium hover:underline">
              Configure
            </Link>
          </CardContent>
        </Card>
      </div>

      {loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : null}

      <AnalystCard />
      <WatcherCard />

      <footer className="flex items-center justify-between border-t border-border pt-3 text-[11px] text-muted-foreground">
        <span>JobPilot · one flow, one account</span>
        <span>Auto-send only when confident</span>
      </footer>
    </main>
  )
}

function AnalystCard() {
  const [insight, setInsight] = useState<Insight | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .insightLatest()
      .then((result) => setInsight(result.insight))
      .catch(() => setInsight(null))
      .finally(() => setLoading(false))
  }, [])

  async function refresh() {
    setRefreshing(true)
    setError('')
    try {
      const result = await api.refreshInsight()
      setInsight(result.insight)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRefreshing(false)
    }
  }

  const payload = insight?.payload
  const newKeywords = payload?.new_keywords ?? []
  const tips = payload?.message_tips ?? []
  const retirements = (payload?.keyword_verdicts ?? []).filter(
    (item) => item.verdict === 'retire',
  )

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <SparklesIcon className="size-4" />
              AI analyst
            </CardTitle>
            <CardDescription>
              ChatGPT reads the agent&apos;s own results: which keywords work, what to try next,
              and how to write better messages.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" disabled={refreshing} onClick={() => void refresh()}>
            {refreshing ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
            {insight ? 'Refresh analysis' : 'Run analysis'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {error ? (
          <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}

        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : insight ? (
          <>
            <p className="text-sm">{insight.summary}</p>

            {newKeywords.length ? (
              <div>
                <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                  New keywords to test
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {newKeywords.map((item) => (
                    <span
                      key={item.keyword}
                      title={item.why}
                      className="rounded-full border border-border px-2.5 py-1 text-xs"
                    >
                      {item.keyword}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {tips.length ? (
              <div>
                <p className="mb-1 text-[11px] font-medium text-muted-foreground">
                  Message advice
                </p>
                <ul className="list-inside list-disc space-y-0.5 text-xs text-muted-foreground">
                  {tips.slice(0, 4).map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <p className="text-[11px] text-muted-foreground">
              {retirements.length ? `${retirements.length} keywords marked for retirement` : 'No keywords marked for retirement'}
              {' · '}
              {insight.created_at ? timeAgo(insight.created_at) : 'just now'}
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            No analysis yet. Add a ChatGPT key in Settings, then press “Run analysis”.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function WatcherCard() {
  const [report, setReport] = useState<WatcherReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .watcherLatest()
      .then((result) => setReport(result.report))
      .catch(() => setReport(null))
      .finally(() => setLoading(false))
  }, [])

  async function checkNow() {
    setChecking(true)
    setError('')
    try {
      const result = await api.watcherCheck()
      setReport(result.report)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setChecking(false)
    }
  }

  const payload = report?.payload
  const health = (payload?.health || '').toLowerCase()
  const badgeVariant =
    health === 'good' ? 'success' : health === 'bad' ? 'destructive' : 'warning'

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <RadarIcon className="size-4" />
              Agent watcher
            </CardTitle>
            <CardDescription>
              Runs in the background, watches what the agent actually did and asks ChatGPT
              whether the outreach is healthy - every ~90 minutes.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {payload?.health ? <Badge variant={badgeVariant}>{payload.health}</Badge> : null}
            <Button size="sm" variant="outline" disabled={checking} onClick={() => void checkNow()}>
              {checking ? <Loader2Icon className="animate-spin" /> : <RadarIcon />}
              {checking ? 'Watching…' : 'Check now'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {error ? (
          <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}

        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : report ? (
          <>
            <p className="text-sm">{payload?.summary || report.summary}</p>

            {payload?.problems?.length ? (
              <div>
                <p className="mb-1 text-[11px] font-medium text-muted-foreground">
                  What went wrong
                </p>
                <ul className="list-inside list-disc space-y-0.5 text-xs text-muted-foreground">
                  {payload.problems.slice(0, 4).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {payload?.next_actions?.length ? (
              <div>
                <p className="mb-1 text-[11px] font-medium text-muted-foreground">Next</p>
                <ul className="list-inside list-disc space-y-0.5 text-xs text-muted-foreground">
                  {payload.next_actions.slice(0, 4).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {payload?.note_for_user ? (
              <p className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs">
                {payload.note_for_user}
              </p>
            ) : null}

            <p className="text-[11px] text-muted-foreground">
              {payload?.activity?.state ? `${payload.activity.state} · ` : ''}
              {report.created_at ? timeAgo(report.created_at) : 'just now'}
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            No report yet. The watcher runs in the background; you can also press “Check now”.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function describeRun(stats: Record<string, unknown>): string {
  const parts: string[] = []
  const add = (key: string, label: string) => {
    const value = stats?.[key]
    if (typeof value === 'number' && value > 0) parts.push(`${value} ${label}`)
  }
  add('posts_seen', 'posts seen')
  add('posts_new', 'new')
  add('duplicates', 'dupes')
  add('relevant', 'relevant')
  add('queued', 'queued')
  add('pending_approval', 'to review')
  add('replied', 'replied')
  add('dm_sent', 'DMs')
  const errors = (stats?.errors as string[] | undefined) || []
  if (errors.length) parts.push(`${errors.length} error`)
  return parts.join(' · ') || 'no changes'
}

function Metric({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: React.ReactNode
  hint: string
}) {
  return (
    <div className="rounded-xl border border-border bg-background/60 p-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-3.5" />
        <p className="text-xs font-medium">{label}</p>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  )
}

function LoopStep({
  icon: Icon,
  title,
  detail,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  detail: string
}) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-border px-3 py-2.5">
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium">{title}</p>
        <p className="text-[11px] leading-snug text-muted-foreground">{detail}</p>
      </div>
    </div>
  )
}
