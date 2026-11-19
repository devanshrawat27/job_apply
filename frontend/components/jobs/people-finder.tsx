'use client'

import { useEffect, useState } from 'react'
import { CopyIcon, Loader2Icon, SparklesIcon, UsersIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { Job } from '@/lib/types'

type People = {
  company: string
  role: string
  queries: string[]
  links: { label: string; query: string; url: string }[]
  message: string
  generated: boolean
}

/** Recruiter / hiring-manager LinkedIn searches for an apply-link job. */
export function PeopleFinder({ job }: { job: Job }) {
  const [data, setData] = useState<People | null>(null)
  const [loading, setLoading] = useState(true)
  const [finding, setFinding] = useState(false)

  useEffect(() => {
    let active = true
    api
      .jobPeople(job.id)
      .then((result) => {
        if (active) setData(result)
      })
      .catch(() => {
        if (active) setData(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [job.id])

  async function find() {
    setFinding(true)
    try {
      const result = await api.findJobPeople(job.id)
      setData(result)
      toast.success('Recruiter searches ready')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setFinding(false)
    }
  }

  async function copy() {
    if (!data?.message) return
    try {
      await navigator.clipboard.writeText(data.message)
      toast.success('Message copied')
    } catch {
      toast.error('Could not copy')
    }
  }

  if (loading) return null

  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/20">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <UsersIcon className="size-3.5 text-muted-foreground" />
          <p className="text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            find people on linkedin
          </p>
          {data?.company ? (
            <span className="text-[11px] text-muted-foreground">· {data.company}</span>
          ) : null}
        </div>
        <div className="flex items-center gap-1.5">
          {data?.message ? (
            <Button size="sm" variant="ghost" onClick={() => void copy()}>
              <CopyIcon />
              Copy message
            </Button>
          ) : null}
          <Button size="sm" variant="outline" disabled={finding} onClick={() => void find()}>
            {finding ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
            {data?.generated ? 'Refresh' : 'Find with ChatGPT'}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2 px-3 py-2">
        {data?.links?.length ? (
          <div className="flex flex-wrap gap-1.5">
            {data.links.map((link) => (
              <a
                key={link.query}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-xs hover:bg-muted/60"
                title={link.query}
              >
                {link.label}
              </a>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            No company name found in this post yet.
          </p>
        )}

        {data?.message ? (
          <p className="whitespace-pre-wrap text-xs text-muted-foreground">{data.message}</p>
        ) : null}
      </div>
    </div>
  )
}
