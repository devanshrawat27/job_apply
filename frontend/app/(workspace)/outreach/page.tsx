'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  ExternalLinkIcon,
  MailIcon,
  MessageSquareIcon,
  ReplyIcon,
  SendIcon,
  UserPlusIcon,
} from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import type { OutreachItem } from '@/lib/types'
import { timeAgo } from '@/lib/utils'

const FILTERS = [
  { key: 'all', label: 'Everything' },
  { key: 'reply', label: 'Replies' },
  { key: 'dm', label: 'DMs' },
  { key: 'email', label: 'Emails' },
  { key: 'apply', label: 'Applied' },
  { key: 'follow', label: 'Follows' },
]

const META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; color: string }
> = {
  reply: { label: 'Public reply', icon: ReplyIcon, color: 'text-emerald-600 dark:text-emerald-400' },
  dm: { label: 'DM', icon: MessageSquareIcon, color: 'text-sky-600 dark:text-sky-400' },
  email: { label: 'Email', icon: MailIcon, color: 'text-violet-600 dark:text-violet-400' },
  apply: { label: 'Applied on site', icon: ExternalLinkIcon, color: 'text-teal-600 dark:text-teal-400' },
  follow: { label: 'Follow', icon: UserPlusIcon, color: 'text-amber-600 dark:text-amber-400' },
}

function statusVariant(status: string) {
  if (status === 'sent') return 'success' as const
  if (status === 'skipped') return 'outline' as const
  if (status === 'unknown') return 'warning' as const
  return 'destructive' as const
}

export default function OutreachPage() {
  const [filter, setFilter] = useState('all')
  const [items, setItems] = useState<OutreachItem[]>([])
  const [summary, setSummary] = useState<{ reply: number; dm: number; email: number; follow: number; apply: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      setError('')
      const [rows, totals] = await Promise.all([api.outreach(filter), api.outreachSummary()])
      setItems(rows)
      setSummary(totals)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    setLoading(true)
    void load()
  }, [load])

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Outreach"
        description="Exactly what the agent sent, to whom, and when."
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="gap-1.5">
              <ReplyIcon className="size-3" />
              {summary?.reply ?? 0}
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <MessageSquareIcon className="size-3" />
              {summary?.dm ?? 0}
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <MailIcon className="size-3" />
              {summary?.email ?? 0}
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <ExternalLinkIcon className="size-3" />
              {summary?.apply ?? 0}
            </Badge>
            <Badge variant="outline" className="gap-1.5">
              <UserPlusIcon className="size-3" />
              {summary?.follow ?? 0}
            </Badge>
          </div>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load the outreach log</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((item) => (
          <Button
            key={item.key}
            size="sm"
            variant={filter === item.key ? 'secondary' : 'ghost'}
            onClick={() => setFilter(item.key)}
          >
            {item.label}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <SendIcon className="mx-auto mb-2 size-5 text-muted-foreground" />
          <p className="text-sm font-medium">Nothing sent yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Once the agent replies, DMs or sends an application email, it shows up here.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card px-4">
          {items.map((item, index) => {
            const meta = META[item.action] ?? META.dm
            const Icon = meta.icon
            const expanded = open === item.id
            return (
              <div
                key={item.id}
                className={`flex gap-3 py-3 ${index < items.length - 1 ? 'border-b border-border/60' : ''}`}
              >
                <span className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg bg-muted ${meta.color}`}>
                  <Icon className="size-3.5" />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{meta.label}</span>
                    <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                    {item.target ? (
                      <span className="text-xs text-muted-foreground">→ {item.target}</span>
                    ) : null}
                    <span className="text-[11px] text-muted-foreground">· {timeAgo(item.created_at)}</span>
                  </div>

                  {(item.role || item.company) && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {[item.role, item.company].filter(Boolean).join(' · ')}
                    </p>
                  )}

                  {item.content ? (
                    <button
                      type="button"
                      onClick={() => setOpen(expanded ? null : item.id)}
                      className="mt-1 block w-full text-left text-xs whitespace-pre-wrap text-muted-foreground hover:text-foreground"
                    >
                      {expanded
                        ? item.content
                        : item.content.length > 160
                          ? `${item.content.slice(0, 160)}…`
                          : item.content}
                    </button>
                  ) : null}

                  {item.detail ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">{item.detail}</p>
                  ) : null}

                  {item.post_url ? (
                    <a
                      href={item.post_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-block text-[11px] underline-offset-4 hover:underline"
                    >
                      open post ↗
                    </a>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </main>
  )
}
