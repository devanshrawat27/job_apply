'use client'

import { useState } from 'react'
import { ExternalLinkIcon, Loader2Icon, SparklesIcon } from 'lucide-react'
import { toast } from 'sonner'

import { JobList } from '@/components/jobs/job-list'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useWorkspace } from '@/lib/use-workspace'

export default function ApplyLinksPage() {
  const { dashboard, reload } = useWorkspace()
  const [refreshKey, setRefreshKey] = useState(0)
  const [filtering, setFiltering] = useState(false)
  const [filterNote, setFilterNote] = useState('')
  const links = dashboard?.apply_links ?? 0

  async function filterWithAi() {
    setFiltering(true)
    setFilterNote('')
    let removed = 0
    try {
      for (let i = 0; i < 20; i += 1) {
        const result = await api.aiFilter({ scope: 'apply_links', limit: 10 })
        removed += result.rejected
        setFilterNote(
          `${removed} removed · ${result.remaining} left to check${
            result.checked ? '' : ' (no verdicts returned)'
          }`,
        )
        if (!result.checked || result.remaining === 0) break
      }
      toast.success(`ChatGPT removed ${removed} mismatched links`)
      await reload()
      setRefreshKey((k) => k + 1)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setFiltering(false)
    }
  }

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Apply links"
        description="Direct apply links — founders and individual hirers are ranked first because they usually reply."
        actions={
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={filtering}
              onClick={() => void filterWithAi()}
            >
              {filtering ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
              {filtering ? 'Filtering…' : 'Filter with ChatGPT'}
            </Button>
            <span className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 text-sm">
              <ExternalLinkIcon className="size-4 text-sky-500" />
              <span className="font-semibold tabular-nums">{links}</span>
              <span className="text-muted-foreground">waiting</span>
            </span>
          </>
        }
      />

      {filterNote ? <p className="text-xs text-muted-foreground">{filterNote}</p> : null}

      <div className="rounded-xl border border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
        {links > 0
          ? `${links} post${links === 1 ? '' : 's'} have an application link and are not applied yet. Open the link, apply on the company site, then hit "Mark applied".`
          : 'No open apply links right now. As new posts are found, any job with a direct link lands here automatically.'}
      </div>

      <JobList
        mode="links"
        refreshKey={refreshKey}
        onChanged={async () => {
          await reload()
          setRefreshKey((k) => k + 1)
        }}
      />
    </main>
  )
}
