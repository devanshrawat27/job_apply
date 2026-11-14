'use client'

import { useState } from 'react'
import {
  AlertTriangleIcon,
  CheckCheckIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CopyIcon,
  ExternalLinkIcon,
  FlagIcon,
  Loader2Icon,
  MailIcon,
  MessageSquareIcon,
  PencilIcon,
  ReplyIcon,
  SendIcon,
  SparklesIcon,
  XIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { PostBody, isLongPost } from '@/components/jobs/post-body'
import { api } from '@/lib/api'
import type { Job } from '@/lib/types'
import { cn, cleanPostText, formatExperience, timeAgo } from '@/lib/utils'

const STATUS: Record<
  string,
  { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'info' }
> = {
  new: { label: 'New', variant: 'secondary' },
  rejected: { label: 'Skipped', variant: 'outline' },
  pending_approval: { label: 'Needs you', variant: 'warning' },
  queued: { label: 'Queued', variant: 'info' },
  sending: { label: 'Sending', variant: 'info' },
  sent: { label: 'Sent', variant: 'success' },
  failed: { label: 'Failed', variant: 'destructive' },
  skipped: { label: 'Skipped', variant: 'outline' },
}

const METHOD: Record<string, { label: string; icon: typeof SendIcon }> = {
  dm: { label: 'apply via DM', icon: MessageSquareIcon },
  reply: { label: 'public reply only', icon: ReplyIcon },
  email: { label: 'apply by email', icon: MailIcon },
  link: { label: 'apply on their site', icon: ExternalLinkIcon },
}

const AUTHOR_LABEL: Record<string, string> = {
  person: 'individual',
  company: 'company',
  job_board: 'job board',
}

function scoreTone(score: number) {
  if (score >= 80) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 65) return 'text-amber-600 dark:text-amber-400'
  return 'text-muted-foreground'
}

export function JobCard({
  job,
  review,
  applyMode = false,
  onChange,
}: {
  job: Job
  review: boolean
  applyMode?: boolean
  onChange: () => Promise<void>
}) {
  const [reply, setReply] = useState(job.reply_text)
  const [dm, setDm] = useState(job.dm_text)
  const [busy, setBusy] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [error, setError] = useState('')

  const meta = STATUS[job.status] ?? { label: job.status, variant: 'outline' as const }
  const method = METHOD[job.outreach_method] ?? METHOD.dm
  const MethodIcon = method.icon
  const canAct = !['sent', 'sending'].includes(job.status)
  const needsYou = job.status === 'pending_approval'
  const linkInPost = Boolean(
    job.apply_url && job.post_url && job.apply_url === job.post_url,
  )

  const cleaned = cleanPostText(job.content || '')
  const longPost = isLongPost(cleaned)

  async function run(label: string, fn: () => Promise<unknown>, message?: string) {
    setBusy(label)
    setError('')
    try {
      await fn()
      await onChange()
      if (message) toast.success(message)
    } catch (err) {
      setError((err as Error).message)
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <article className="overflow-hidden rounded-xl border border-border bg-card transition-colors hover:border-foreground/20">
      {needsYou ? (
        <div className="flex items-start gap-2 border-b border-amber-500/20 bg-amber-500/[0.06] px-4 py-2.5">
          <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-xs leading-relaxed text-amber-800 dark:text-amber-200">
            <span className="font-medium">Why this needs you: </span>
            {job.uncertainties?.length
              ? job.uncertainties.slice(0, 2).join(' · ')
              : job.decision_reason && !/^confidence \d/i.test(job.decision_reason)
                ? job.decision_reason
                : 'The agent was not sure enough to send this on its own.'}
          </p>
          <span className="ml-auto shrink-0 text-[10px] text-amber-700/80 dark:text-amber-300/80">
            confidence {Math.round((job.confidence || 0) * 100)}%
          </span>
        </div>
      ) : null}

      <div className="p-4">
        {/* header */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium">{job.author_name || job.author_handle}</span>
              <span className="text-xs text-muted-foreground">@{job.author_handle}</span>
              <span className="text-xs text-muted-foreground">
                · {timeAgo(job.posted_at || job.discovered_at)}
              </span>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              {job.company ? <span className="font-medium text-foreground">{job.company}</span> : null}
              {job.role ? <span>{job.role}</span> : null}
              {job.job_location ? <span>· {job.job_location}</span> : null}
              <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px]">
                <MethodIcon className="size-3" />
                {method.label}
              </span>
              {applyMode && job.author_type === 'person' ? (
                <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
                  direct hire
                </span>
              ) : null}
              {job.resume_label ? (
                <span className="text-[11px]">resume: {job.resume_label}</span>
              ) : null}
              {job.required_experience_months > 0 ? (
                <span className="text-[11px]">
                  needs {formatExperience(job.required_experience_months)}
                </span>
              ) : null}
              <span
                className={cn(
                  'text-[11px]',
                  job.author_type === 'person' ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground',
                )}
                title={
                  job.author_type === 'job_board'
                    ? 'Job-board accounts rarely read DMs, so the agent only replies publicly'
                    : job.author_type === 'company'
                      ? 'Company account'
                      : 'Individual person'
                }
              >
                {AUTHOR_LABEL[job.author_type] || 'individual'}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <span className={cn('text-xl font-semibold tabular-nums', scoreTone(job.relevance))}>
              {job.relevance}
            </span>
            <Badge variant={meta.variant}>{meta.label}</Badge>
            {job.ai_fit >= 0 ? (
              <Badge variant="info" title={job.ai_note || 'ChatGPT job-fit score'}>
                AI fit {job.ai_fit}
              </Badge>
            ) : null}
            {job.incoming_reply_at ? (
              <Badge variant="success" title={job.incoming_reply_text || 'They replied'}>
                Replied
              </Badge>
            ) : null}
          </div>
        </div>

        {/* post text */}
        <PostBody text={cleaned} expanded={expanded} />
        {longPost ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {expanded ? <ChevronUpIcon className="size-3" /> : <ChevronDownIcon className="size-3" />}
            {expanded ? 'Show less' : 'Show full post'}
          </button>
        ) : null}

        {/* apply target */}
        {job.apply_url && (job.outreach_method === 'link' || applyMode) ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-muted-foreground">
                {linkInPost ? 'Application link is inside the post' : 'Application link'}
              </p>
              <a
                href={job.apply_url}
                target="_blank"
                rel="noreferrer"
                className="block truncate text-xs underline-offset-4 hover:underline"
              >
                {linkInPost ? 'Open the post on X' : job.apply_url}
              </a>
            </div>
            <a
              href={job.apply_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/80"
            >
              <ExternalLinkIcon className="size-3.5" />
              {linkInPost ? 'Open post' : 'Apply on site'}
            </a>
          </div>
        ) : null}

        {job.outreach_method === 'link' && !job.apply_url ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-sky-500/25 bg-sky-500/5 px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-sky-700 dark:text-sky-300">
                Application link is inside the post
              </p>
              <p className="text-xs text-muted-foreground">
                X kept the URL in the post&apos;s link card, so nothing is sent automatically.
              </p>
            </div>
            <a
              href={job.post_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/80"
            >
              <ExternalLinkIcon className="size-3.5" />
              Open post
            </a>
          </div>
        ) : null}

        {job.outreach_method === 'email' && job.contact_email ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-muted-foreground">Email application</p>
              <a href={`mailto:${job.contact_email}`} className="block truncate text-xs hover:underline">
                {job.contact_email}
              </a>
            </div>
            <a
              href={`mailto:${job.contact_email}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-background px-3 text-sm font-medium hover:bg-muted"
            >
              <MailIcon className="size-3.5" />
              Email them
            </a>
          </div>
        ) : null}

        {/* drafts */}
        {job.reply_text || job.dm_text ? (
          <div className="mt-3 grid gap-2">
            {job.reply_text ? (
              <div className="rounded-lg border border-border border-l-2 border-l-emerald-500/70 bg-muted/30 px-3 py-2">
                <p className="mb-1 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
                  public reply
                </p>
                {review && editing ? (
                  <Textarea value={reply} onChange={(e) => setReply(e.target.value)} className="text-sm" />
                ) : (
                  <p className="text-sm whitespace-pre-wrap">{job.reply_text}</p>
                )}
              </div>
            ) : null}

            {job.dm_text ? (
              <div className="rounded-lg border border-border border-l-2 border-l-sky-500/70 bg-muted/30 px-3 py-2">
                <p className="mb-1 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
                  dm to @{job.author_handle}
                </p>
                {review && editing ? (
                  <Textarea value={dm} onChange={(e) => setDm(e.target.value)} className="text-sm" />
                ) : (
                  <p className="text-sm whitespace-pre-wrap">{job.dm_text}</p>
                )}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* warnings */}
        {job.spam_score >= 40 ? (
          <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-500/25 bg-amber-500/5 px-2.5 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
            <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>
              looks like a fake post ({job.spam_score}/100)
              {job.spam_reasons?.length ? ` — ${job.spam_reasons.join(' · ')}` : ''}
            </span>
          </p>
        ) : null}

        {job.generic_draft ? (
          <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-500/25 bg-amber-500/5 px-2.5 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
            <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
            <span>the draft reads generic — edit it so it references this post</span>
          </p>
        ) : null}

        {job.last_error ? (
          <p className="mt-2 text-[11px] text-destructive">{job.last_error}</p>
        ) : null}
        {error ? <p className="mt-2 text-[11px] text-destructive">{error}</p> : null}

        {/* footer */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <a
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            href={job.post_url}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLinkIcon className="size-3.5" />
            post
          </a>

          {review && canAct && job.outreach_method !== 'email' ? (
            <>
              {job.outreach_method === 'dm' ? (
                <Button variant="ghost" size="sm" onClick={() => setEditing((v) => !v)}>
                  <PencilIcon />
                  {editing ? 'Done' : 'Edit'}
                </Button>
              ) : null}

              {job.outreach_method === 'link' && job.apply_url ? (
                <a
                  href={job.apply_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2.5 text-[0.8rem] font-medium hover:bg-muted"
                >
                  <ExternalLinkIcon className="size-3.5" />
                  {linkInPost ? 'Open post' : 'Apply on site'}
                </a>
              ) : null}

              <Button
                variant="destructive"
                size="sm"
                disabled={busy !== null}
                onClick={() => run('reject', () => api.decide(job.id, { approved: false }), 'Rejected')}
              >
                {busy === 'reject' ? <Loader2Icon className="animate-spin" /> : <XIcon />}
                Reject
              </Button>

              {job.outreach_method !== 'link' ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => run('redraft', () => api.redraftJob(job.id), 'Redrafted with ChatGPT')}
                >
                  {busy === 'redraft' ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
                  Redraft
                </Button>
              ) : null}

              {job.outreach_method !== 'link' ? (
                <Button
                  size="sm"
                  disabled={busy !== null}
                  onClick={() =>
                    run(
                      'send',
                      () =>
                        api.sendNow(job.id, {
                          reply_text: editing ? reply : undefined,
                          dm_text: editing ? dm : undefined,
                        }),
                      'Approved — sending now (or right after the cool-down)',
                    )
                  }
                >
                  {busy === 'send' ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
                  Approve &amp; send
                </Button>
              ) : null}

              {job.outreach_method === 'link' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() => run('applied', () => api.markApplied(job.id), 'Marked as applied')}
                >
                  {busy === 'applied' ? <Loader2Icon className="animate-spin" /> : <CheckCheckIcon />}
                  Mark applied
                </Button>
              ) : null}
            </>
          ) : null}

          {review && canAct && job.outreach_method === 'email' ? (
            <>
              <Button
                variant="destructive"
                size="sm"
                disabled={busy !== null}
                onClick={() => run('reject', () => api.decide(job.id, { approved: false }), 'Rejected')}
              >
                {busy === 'reject' ? <Loader2Icon className="animate-spin" /> : <XIcon />}
                Reject
              </Button>
              <Button
                size="sm"
                disabled={busy !== null}
                onClick={() => run('applied', () => api.markApplied(job.id), 'Marked as applied')}
              >
                {busy === 'applied' ? <Loader2Icon className="animate-spin" /> : <CheckCheckIcon />}
                Mark applied
              </Button>
            </>
          ) : null}

          {applyMode && job.apply_url ? (
            <>
              <a
                href={job.apply_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md bg-primary px-2.5 text-[0.8rem] font-medium text-primary-foreground hover:bg-primary/80"
              >
                <ExternalLinkIcon className="size-3.5" />
                {linkInPost ? 'Open post' : 'Apply on site'}
              </a>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy !== null}
                onClick={() => run('applied', () => api.markApplied(job.id), 'Marked as applied')}
              >
                {busy === 'applied' ? <Loader2Icon className="animate-spin" /> : <CheckCheckIcon />}
                Mark applied
              </Button>
              <Button
                variant="destructive"
                size="sm"
                disabled={busy !== null}
                onClick={() => run('reject', () => api.decide(job.id, { approved: false }), 'Rejected')}
              >
                {busy === 'reject' ? <Loader2Icon className="animate-spin" /> : <XIcon />}
                Reject
              </Button>
            </>
          ) : null}

          {!review && canAct && job.status === 'queued' ? (
            <Button size="sm" disabled={busy !== null} onClick={() => run('send', () => api.sendNow(job.id), 'Sending now')}>
              {busy === 'send' ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
              Send now
            </Button>
          ) : null}

          {!review && canAct && job.dm_status === 'skipped' && job.dm_text ? (
            <Button
              size="sm"
              disabled={busy !== null}
              onClick={() => run('retry', () => api.retryDm(job.id), 'DM retry queued')}
            >
              {busy === 'retry' ? <Loader2Icon className="animate-spin" /> : <MessageSquareIcon />}
              Retry DM
            </Button>
          ) : null}

          {job.dm_text && job.outreach_method !== 'email' ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(job.dm_text)
                    .then(() => toast.success('DM copied — paste it in X'))
                    .catch(() => toast.error('Could not copy'))
                }}
              >
                <CopyIcon />
                Copy DM
              </Button>
              <a
                href="https://x.com/messages"
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[0.8rem] text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <MessageSquareIcon className="size-3.5" />
                Open chat
              </a>
            </>
          ) : null}

          {job.logs?.length ? (
            <button
              type="button"
              onClick={() => setShowLogs((v) => !v)}
              className="ml-auto text-[11px] text-muted-foreground hover:text-foreground"
            >
              {showLogs ? 'hide details' : 'details'}
            </button>
          ) : null}

          {canAct ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy !== null}
              onClick={() => run('fake', () => api.reportFake(job.id), 'Reported as fake')}
              title="Mark as fake and block this account"
            >
              {busy === 'fake' ? <Loader2Icon className="animate-spin" /> : <FlagIcon />}
              Fake
            </Button>
          ) : null}
        </div>

        {showLogs ? (
          <div className="mt-2 space-y-2">
            <p className="text-[11px] text-muted-foreground">
              <span className="font-medium">why scored {job.relevance}: </span>
              {job.reason || '—'}
              <span className="mx-1.5">·</span>
              confidence {Math.round(job.confidence * 100)}%
            </p>
            {job.logs?.length ? (
              <pre className="max-h-32 overflow-auto rounded-lg border border-border bg-background p-2 font-mono text-[11px] whitespace-pre-wrap text-muted-foreground">
                {job.logs.join('\n')}
              </pre>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  )
}
