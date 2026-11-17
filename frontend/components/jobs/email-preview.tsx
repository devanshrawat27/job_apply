'use client'

import { useEffect, useState } from 'react'
import {
  CheckIcon,
  Loader2Icon,
  PaperclipIcon,
  PencilIcon,
  SparklesIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Job } from '@/lib/types'

type Preview = {
  to: string
  subject: string
  body: string
  attachment: string
  resume_id: number
  resumes: { id: number; label: string; filename: string }[]
}

/** The exact email that will be sent, editable before sending. */
export function EmailPreview({
  job,
  canAct,
  onChanged,
}: {
  job: Job
  canAct: boolean
  onChanged: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [loading, setLoading] = useState(true)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const data = await api.emailPreview(job.id)
      setPreview(data)
      setSubject(data.subject)
      setBody(data.body)
    } catch {
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id])

  async function save() {
    setBusy('save')
    try {
      await api.saveEmailDraft(job.id, { subject, body })
      setEditing(false)
      toast.success('Email saved')
      onChanged()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function redraft() {
    setBusy('redraft')
    try {
      await api.redraftJob(job.id)
      await load()
      toast.success('Redrafted with ChatGPT')
      onChanged()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function attach(resumeId: number) {
    setBusy('attach')
    try {
      await api.setJobResume(job.id, resumeId)
      await load()
      toast.success('Resume attached')
      onChanged()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <Loader2Icon className="size-3.5 animate-spin" />
        Preparing the email…
      </div>
    )
  }

  if (!preview) {
    return null
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/20">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            email preview
          </p>
          <p className="truncate text-xs">
            To <span className="font-medium">{preview.to}</span>
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {canAct ? (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy !== null}
              onClick={() => (editing ? void save() : setEditing(true))}
            >
              {busy === 'save' ? (
                <Loader2Icon className="animate-spin" />
              ) : editing ? (
                <CheckIcon />
              ) : (
                <PencilIcon />
              )}
              {editing ? 'Save' : 'Edit'}
            </Button>
          ) : null}
          {canAct ? (
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void redraft()}>
              {busy === 'redraft' ? <Loader2Icon className="animate-spin" /> : <SparklesIcon />}
              Redraft
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-2 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <PaperclipIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="text-muted-foreground">Resume</span>
          {preview.resumes.length ? (
            <select
              value={preview.resume_id}
              disabled={!canAct || busy !== null}
              onChange={(e) => void attach(Number(e.target.value))}
              className="h-7 max-w-[260px] rounded-md border border-input bg-transparent px-2 text-xs outline-none dark:bg-input/30"
            >
              <option value={0}>{preview.attachment || 'choose a resume'}</option>
              {preview.resumes.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resume.label}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-xs">{preview.attachment || 'no resume uploaded'}</span>
          )}
          {busy === 'attach' ? <Loader2Icon className="size-3 animate-spin" /> : null}
        </div>

        <div>
          <p className="text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            subject
          </p>
          {editing ? (
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} className="mt-1 h-8 text-sm" />
          ) : (
            <p className="text-sm">{preview.subject}</p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
            body
          </p>
          {editing ? (
            <Textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="mt-1 min-h-[180px] text-sm"
            />
          ) : (
            <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">{preview.body}</pre>
          )}
        </div>
      </div>
    </div>
  )
}
