'use client'

import { useRef, useState } from 'react'
import { FileTextIcon, Loader2Icon, UploadCloudIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Field } from '@/components/profile/fields'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Profile } from '@/lib/types'

export function ResumeUploader({
  profile,
  onUploaded,
  compact = false,
}: {
  profile: Profile
  onUploaded: (profile: Profile) => Promise<void> | void
  compact?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function upload(file: File | null) {
    if (!file) return
    setUploading(true)
    try {
      const result = await api.uploadResume(file)
      await onUploaded(await api.getProfile())
      const count = Array.isArray(result.extracted?.skills)
        ? (result.extracted.skills as string[]).length
        : 0
      toast.success('Resume read', {
        description: `${result.chars.toLocaleString()} characters${
          count ? ` · ${count} skills picked up` : ''
        }`,
      })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div
      className={
        compact
          ? 'flex flex-wrap items-center gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3'
          : 'rounded-xl border border-dashed border-border bg-muted/10 p-6'
      }
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt,.md"
        className="hidden"
        onChange={(e) => upload(e.target.files?.[0] ?? null)}
      />

      {compact ? (
        <>
          <FileTextIcon className="size-4 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {profile.resume_filename || 'No resume uploaded'}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Upload a new file to re-extract your details.
            </p>
          </div>
          <Button variant="outline" size="sm" disabled={uploading} onClick={() => inputRef.current?.click()}>
            {uploading ? <Loader2Icon className="animate-spin" /> : null}
            Replace
          </Button>
        </>
      ) : (
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="grid size-10 place-items-center rounded-full bg-muted text-muted-foreground">
            {uploading ? <Loader2Icon className="size-5 animate-spin" /> : <UploadCloudIcon className="size-5" />}
          </span>
          <div>
            <p className="text-sm font-medium">
              {uploading ? 'Reading your resume…' : 'Upload your resume'}
            </p>
            <p className="text-xs text-muted-foreground">
              PDF, DOCX, TXT or MD. We fill in your details so you do not have to type them.
            </p>
          </div>
          <Button disabled={uploading} onClick={() => inputRef.current?.click()}>
            {uploading ? 'Reading…' : 'Choose file'}
          </Button>
          {profile.resume_filename ? (
            <p className="text-[11px] text-muted-foreground">
              Current: {profile.resume_filename}
            </p>
          ) : null}
        </div>
      )}
    </div>
  )
}

export function ExperienceInput({
  months,
  onChange,
}: {
  months: number
  onChange: (months: number) => void
}) {
  const total = Math.max(0, Math.floor(months || 0))
  const years = Math.floor(total / 12)
  const rest = total % 12

  return (
    <div className="flex items-center gap-2">
      <Input
        type="number"
        min={0}
        max={50}
        value={years}
        onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0) * 12 + rest)}
        className="w-20"
        aria-label="Years of experience"
      />
      <span className="text-xs text-muted-foreground">yrs</span>
      <Input
        type="number"
        min={0}
        max={11}
        value={rest}
        onChange={(e) =>
          onChange(years * 12 + Math.min(11, Math.max(0, Number(e.target.value) || 0)))
        }
        className="w-20"
        aria-label="Additional months of experience"
      />
      <span className="text-xs text-muted-foreground">mo</span>
    </div>
  )
}

export function CandidateFields({
  profile,
  onChange,
}: {
  profile: Profile
  onChange: (patch: Partial<Profile>) => void
}) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name">
          <Input
            value={profile.full_name}
            onChange={(e) => onChange({ full_name: e.target.value })}
            placeholder="Your name"
          />
        </Field>
        <Field label="Email">
          <Input
            type="email"
            value={profile.email}
            onChange={(e) => onChange({ email: e.target.value })}
            placeholder="you@email.com"
          />
        </Field>
        <Field label="Phone">
          <Input
            value={profile.phone}
            onChange={(e) => onChange({ phone: e.target.value })}
            placeholder="+91 …"
          />
        </Field>
        <Field label="Location">
          <Input
            value={profile.location}
            onChange={(e) => onChange({ location: e.target.value })}
            placeholder="City, State"
          />
        </Field>
        <Field label="Current role">
          <Input
            value={profile.current_role}
            onChange={(e) => onChange({ current_role: e.target.value })}
            placeholder="Frontend Developer"
          />
        </Field>
        <Field label="Current company">
          <Input
            value={profile.current_company}
            onChange={(e) => onChange({ current_company: e.target.value })}
            placeholder="Company or Freelance"
          />
        </Field>
      </div>

      <Field
        label="Total experience"
        hint="Months supported — 4 months is a valid answer."
      >
        <ExperienceInput
          months={profile.experience_months}
          onChange={(experience_months) => onChange({ experience_months })}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="GitHub">
          <Input
            value={profile.links?.github || ''}
            onChange={(e) => onChange({ links: { ...profile.links, github: e.target.value } })}
            placeholder="github.com/you"
          />
        </Field>
        <Field label="Portfolio">
          <Input
            value={profile.links?.portfolio || ''}
            onChange={(e) => onChange({ links: { ...profile.links, portfolio: e.target.value } })}
            placeholder="yoursite.dev"
          />
        </Field>
        <Field label="LinkedIn">
          <Input
            value={profile.links?.linkedin || ''}
            onChange={(e) => onChange({ links: { ...profile.links, linkedin: e.target.value } })}
            placeholder="linkedin.com/in/you"
          />
        </Field>
      </div>
    </div>
  )
}
