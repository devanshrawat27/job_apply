'use client'

import { useState } from 'react'
import { Loader2Icon, SearchIcon } from 'lucide-react'
import { toast } from 'sonner'

import { JobList } from '@/components/jobs/job-list'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useWorkspace } from '@/lib/use-workspace'
import { timeAgo } from '@/lib/utils'

export default function PostsPage() {
  const { dashboard, settings, reload } = useWorkspace()
  const [refreshKey, setRefreshKey] = useState(0)
  const [scanning, setScanning] = useState(false)

  const interval = settings?.scan_interval_minutes ?? 30

  async function scan() {
    setScanning(true)
    try {
      await api.scanNow()
      toast.success('Scan started', { description: 'Fresh posts appear as they are found.' })
      setTimeout(() => setRefreshKey((k) => k + 1), 4000)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setScanning(false)
    }
  }

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Found posts"
        description="Every hiring post the agent read on X, newest first."
        actions={
          <Button size="sm" disabled={scanning} onClick={() => void scan()}>
            {scanning ? <Loader2Icon className="animate-spin" /> : <SearchIcon />}
            Scan now
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border bg-muted/20 px-4 py-2.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
          Auto-scan every <span className="font-medium text-foreground">{interval} min</span>
        </span>
        <span>last scan {timeAgo(dashboard?.agent.last_scan ?? null)}</span>
        <span className="hidden sm:inline">
          · scanning runs by itself — “Scan now” is only a manual override
        </span>
      </div>

      <JobList
        mode="all"
        refreshKey={refreshKey}
        onChanged={async () => {
          await reload()
          setRefreshKey((k) => k + 1)
        }}
      />
    </main>
  )
}
