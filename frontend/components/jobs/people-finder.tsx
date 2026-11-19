'use client'

import { useEffect, useState } from 'react'
import { Loader2Icon, SearchIcon, UsersIcon } from 'lucide-react'
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
      if (result.links?.length) {
        toast.success('LinkedIn searches ready')
      } else {
        toast.info('Could not find a company name in this post')
      }
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setFinding(false)
    }
  }

  if (loading) return null

  const links = data?.links ?? []
  const hasLinks = links.length > 0

  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/20">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <UsersIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <p className="text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            find people on linkedin
          </p>
          {data?.company ? (
            <span className="truncate text-[11px] text-muted-foreground">
              · {data.company}
              {data.role ? ` · ${data.role}` : ''}
            </span>
          ) : null}
        </div>
        <Button size="sm" variant="outline" disabled={finding} onClick={() => void find()}>
          {hasLinks ? <SearchIcon /> : <UsersIcon />}
          Find
        </Button>
      </div>

      {finding ? (
        <div className="flex items-center gap-2 border-t border-border px-3 py-3 text-xs text-muted-foreground">
          <Loader2Icon className="size-3.5 animate-spin" />
          Searching recruiters and hiring managers…
        </div>
      ) : hasLinks ? (
        <div className="flex flex-wrap gap-1.5 border-t border-border px-3 py-2.5">
          {links.map((link) => (
            <a
              key={link.query}
              href={link.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium hover:bg-muted/60"
              title={link.query}
            >
              {link.label}
            </a>
          ))}
        </div>
      ) : (
        <p className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
          Press Find to search LinkedIn for recruiters at this company.
        </p>
      )}
    </div>
  )
}
