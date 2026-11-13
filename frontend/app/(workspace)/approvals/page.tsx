'use client'

import { useState, useEffect } from 'react'
import { Loader2Icon, SendIcon, SparklesIcon } from 'lucide-react'
import { toast } from 'sonner'

import { JobList } from '@/components/jobs/job-list'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useWorkspace } from '@/lib/use-workspace'

export default function ApprovalsPage() {
  const { dashboard, reload } = useWorkspace()
  const [refreshKey, setRefreshKey] = useState(0)
  const [llmReady, setLlmReady] = useState<boolean | null>(null)
  const [filtering, setFiltering] = useState(false)
  const [filterNote, setFilterNote] = useState('')

  useEffect(() => {
    api
      .health()
      .then((health) => setLlmReady(health.llm_configured))
      .catch(() => setLlmReady(null))
  }, [])

  async function sendQueued() {
    try {
      await api.sendQueued()
      toast.success('Send run started')
      setTimeout(() => setRefreshKey((k) => k + 1), 4000)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function filterWithAi() {
    setFiltering(true)
    setFilterNote('')
    let removed = 0
    try {
      for (let i = 0; i < 20; i += 1) {
        const result = await api.aiFilter({ scope: 'pending', limit: 10 })
        removed += result.rejected
        setFilterNote(
          `${removed} removed · ${result.remaining} left to check${
            result.checked ? '' : ' (no verdicts returned)'
          }`,
        )
        if (!result.checked || result.remaining === 0) break
      }
      toast.success(`ChatGPT removed ${removed} mismatched posts`)
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
        title="Approvals"
        description="The agent stops here whenever it is not sure. Review, edit or reject."
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
            <Button size="sm" variant="outline" onClick={() => void sendQueued()}>
              <SendIcon />
              Send queued
            </Button>
          </>
        }
      />

      {filterNote ? (
        <p className="text-xs text-muted-foreground">{filterNote}</p>
      ) : null}

      <div className="rounded-xl border border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
        {dashboard?.pending_approvals
          ? `${dashboard.pending_approvals} post${
              dashboard.pending_approvals > 1 ? 's' : ''
            } need a decision from you.`
          : 'Nothing waiting right now. The agent only stops when it needs you.'}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
          <span>• the post asks you to apply on an external link</span>
          <span>• email application, but email is not set up</span>
          <span>• the draft was not confident or read generic</span>
          <span>• it might be a fake post</span>
        </div>
      </div>

      {llmReady === false ? (
        <Alert>
          <AlertTitle>Everything waits here because no LLM key is set</AlertTitle>
          <AlertDescription>
            Without a model the agent can only write template drafts (confidence 0.35), so it
            never auto-sends and every post needs you. Add <code>LLM_API_KEY</code> to{' '}
            <code>backend/.env</code>, restart the backend, and confident matches will apply
            on their own. Posts with an external link will still wait for you.
          </AlertDescription>
        </Alert>
      ) : null}

      <JobList
        mode="review"
        refreshKey={refreshKey}
        onChanged={async () => {
          await reload()
          setRefreshKey((k) => k + 1)
        }}
      />
    </main>
  )
}
