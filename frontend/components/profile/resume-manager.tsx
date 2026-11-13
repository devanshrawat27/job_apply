'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2Icon, FileTextIcon, Loader2Icon, PlusIcon, Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { ResumeDoc } from '@/lib/types'

export function ResumeManager({ onChanged }: { onChanged: () => Promise<void> }) {
  const [resumes, setResumes] = useState<ResumeDoc[]>([])
  const [label, setLabel] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      setResumes(await api.resumes())
    } catch {
      setResumes([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function upload(file: File | null) {
    if (!file) return
    setBusy('upload')
    try {
      await api.addResume(file, label.trim(), resumes.length === 0)
      setLabel('')
      await load()
      await onChanged()
      toast.success('Resume added')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy('')
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function promote(id: number) {
    setBusy(`primary-${id}`)
    try {
      await api.makePrimaryResume(id)
      await load()
      await onChanged()
      toast.success('Primary resume updated')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function remove(id: number) {
    setBusy(`delete-${id}`)
    try {
      await api.deleteResume(id)
      await load()
      await onChanged()
      toast.success('Resume removed')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Keep more than one resume. For every post the agent picks the one whose text matches
        the post best, and attaches that file when it emails.
      </p>

      {loading ? (
        <div className="text-xs text-muted-foreground">Loading resumes…</div>
      ) : resumes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
          No resume yet. Add one and your profile fields get filled automatically.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {resumes.map((resume) => (
            <div
              key={resume.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-muted/20 px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{resume.label}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {resume.filename} · {resume.chars.toLocaleString()} chars
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {resume.is_primary ? (
                  <Badge variant="success" className="gap-1.5">
                    <CheckCircle2Icon className="size-3" />
                    primary
                  </Badge>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy !== ''}
                    onClick={() => void promote(resume.id)}
                  >
                    {busy === `primary-${resume.id}` ? (
                      <Loader2Icon className="animate-spin" />
                    ) : null}
                    Make primary
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy !== ''}
                  onClick={() => void remove(resume.id)}
                  aria-label={`Delete ${resume.label}`}
                >
                  {busy === `delete-${resume.id}` ? (
                    <Loader2Icon className="animate-spin" />
                  ) : (
                    <Trash2Icon />
                  )}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.txt,.md"
        className="hidden"
        onChange={(e) => upload(e.target.files?.[0] ?? null)}
      />

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[180px] flex-1">
          <label className="mb-1 block text-[11px] text-muted-foreground">
            Label (optional) — e.g. “Frontend”, “AI / Agentic”
          </label>
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Backend resume"
          />
        </div>
        <Button disabled={busy !== ''} onClick={() => fileRef.current?.click()}>
          {busy === 'upload' ? <Loader2Icon className="animate-spin" /> : <PlusIcon />}
          Add resume
        </Button>
      </div>
    </div>
  )
}
