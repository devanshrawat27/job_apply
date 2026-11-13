'use client'

import { useState } from 'react'
import {
  CheckIcon,
  Loader2Icon,
  MessageSquareIcon,
  ReplyIcon,
  SearchIcon,
  ShieldCheckIcon,
  UserPlusIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Field } from '@/components/profile/fields'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { Account } from '@/lib/types'
import { cn } from '@/lib/utils'

const CAPABILITIES = [
  {
    id: 'search',
    label: 'Find hiring posts',
    description: 'Read X search results for fresh job posts.',
    icon: SearchIcon,
    locked: true,
  },
  {
    id: 'reply',
    label: 'Post a public reply',
    description: 'Reply to the hiring post from your account.',
    icon: ReplyIcon,
    locked: false,
  },
  {
    id: 'dm',
    label: 'Send a personal DM',
    description: 'Message the poster after the reply.',
    icon: MessageSquareIcon,
    locked: false,
  },
  {
    id: 'follow',
    label: 'Follow when needed',
    description: 'Only if X blocks the DM until you follow.',
    icon: UserPlusIcon,
    locked: false,
  },
] as const

export function ConnectXForm({
  onConnected,
  allowReply,
  allowDm,
  allowFollow,
  onAllowReply,
  onAllowDm,
  onAllowFollow,
  submitLabel = 'Connect account',
}: {
  onConnected: (account: Account) => void
  allowReply: boolean
  allowDm: boolean
  allowFollow: boolean
  onAllowReply: (value: boolean) => void
  onAllowDm: (value: boolean) => void
  onAllowFollow: (value: boolean) => void
  submitLabel?: string
}) {
  const [handle, setHandle] = useState('')
  const [password, setPassword] = useState('')
  const [verificationCode, setVerificationCode] = useState('')
  const [dmPasscode, setDmPasscode] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const enabled = { search: true, reply: allowReply, dm: allowDm, follow: allowFollow }
  const setEnabled = (id: 'search' | 'reply' | 'dm' | 'follow', value: boolean) => {
    if (id === 'reply') onAllowReply(value)
    if (id === 'dm') onAllowDm(value)
    if (id === 'follow') onAllowFollow(value)
  }

  async function connect() {
    const clean = handle.trim().replace(/^@/, '')
    if (!clean) return setError('Enter the X handle you want the agent to use.')
    if (!password) return setError('Enter your X password so the agent can sign in.')

    setSaving(true)
    setError(null)
    try {
      const account = await api.connect({
        username: clean,
        password,
        verification_code: verificationCode.trim() || undefined,
        dm_passcode: allowDm ? dmPasscode.trim() || undefined : undefined,
      })
      setPassword('')
      setVerificationCode('')
      setDmPasscode('')
      toast.success(`@${account.username} connected`)
      onConnected(account)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="X handle" hint="The account the agent will use.">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">@</span>
            <Input
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="yourhandle"
              maxLength={16}
              className="h-10 rounded-xl"
            />
          </div>
        </Field>

        <Field
          label="X password"
          hint="A browser window opens and signs in for you. The password is never stored."
        >
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your X password"
            className="h-10 rounded-xl"
          />
        </Field>

        <Field
          label="Verification code"
          hint="Only if X asks for an email, phone or 2FA code."
        >
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value)}
            placeholder="Optional"
            className="h-10 rounded-xl"
          />
        </Field>

        {allowDm ? (
          <Field
            label="X chat passcode"
            hint="Optional. Only needed if X asks for a passcode when sending a DM — leave it empty and the agent will just try."
          >
            <Input
              type="password"
              autoComplete="off"
              value={dmPasscode}
              onChange={(e) => setDmPasscode(e.target.value)}
              placeholder="Optional"
              className="h-10 rounded-xl"
            />
          </Field>
        ) : (
          <div className="hidden sm:block" />
        )}
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">What the agent will do</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {CAPABILITIES.map((cap) => {
            const active = enabled[cap.id]
            return (
              <button
                key={cap.id}
                type="button"
                disabled={cap.locked}
                onClick={() => setEnabled(cap.id, !active)}
                className={cn(
                  'flex items-start gap-2 rounded-xl border px-3 py-2.5 text-left text-xs transition-colors',
                  active
                    ? 'border-foreground/30 bg-foreground/5'
                    : 'border-border bg-transparent text-muted-foreground hover:bg-muted/40',
                  cap.locked ? 'cursor-default' : '',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 grid size-4 shrink-0 place-items-center rounded-sm border',
                    active ? 'border-foreground bg-foreground text-background' : 'border-border',
                  )}
                >
                  {active ? <CheckIcon className="size-3" /> : null}
                </span>
                <span>
                  <span className="flex items-center gap-1.5 font-medium text-foreground">
                    <cap.icon className="size-3.5" />
                    {cap.label}
                  </span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {cap.description}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-muted-foreground">
        <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <p>
          The agent signs in to X with the handle and password above, then stores only the
          resulting session cookies (encrypted). Your password is not stored and is never
          returned by the API. The chat passcode is used only to unlock encrypted DMs.
        </p>
      </div>

      <div className="flex justify-end">
        <Button onClick={() => void connect()} disabled={saving}>
          {saving ? <Loader2Icon className="animate-spin" /> : null}
          {saving ? 'Opening browser…' : submitLabel}
        </Button>
      </div>
    </div>
  )
}
