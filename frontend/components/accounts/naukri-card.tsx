'use client'

import { useEffect, useState } from 'react'
import { BriefcaseIcon, CheckCircle2Icon, ExternalLinkIcon, Loader2Icon, Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/profile/fields'
import { api } from '@/lib/api'
import type { NaukriAccount } from '@/lib/types'

export function NaukriCard() {
  const [account, setAccount] = useState<NaukriAccount | null>(null)
  const [loading, setLoading] = useState(true)
  const [replacing, setReplacing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')

  async function load() {
    try {
      setAccount(await api.naukriAccount())
    } catch {
      setAccount(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function connect() {
    setSaving(true)
    setError('')
    toast.info('A Chrome window is opening. Sign in to Naukri there — waiting up to 5 minutes.')
    try {
      const saved = await api.connectNaukri(email.trim())
      setAccount(saved)
      setReplacing(false)
      toast.success('Naukri connected', {
        description: 'Fresh Naukri jobs will now appear in Apply links for review.',
      })
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function disconnect() {
    if (!account) return
    try {
      await api.disconnectNaukri(account.id)
      setAccount(null)
      toast.success('Naukri disconnected')
    } catch (cause) {
      toast.error((cause as Error).message)
    }
  }

  async function openWindow() {
    try {
      await api.naukriWindow()
      toast.success('Naukri window opened', {
        description: 'Use it to see applied jobs or finish a question form.',
      })
    } catch (cause) {
      toast.error((cause as Error).message)
    }
  }

  const showForm = !account || replacing

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BriefcaseIcon className="size-4 text-orange-500" />
          Naukri.com
          {account ? (
            <Badge
              variant={account.status === 'connected' ? 'success' : 'destructive'}
              className="ml-1 gap-1"
            >
              {account.status === 'connected' ? (
                <CheckCircle2Icon className="size-3" />
              ) : null}
              {account.status === 'blocked'
                ? 'Blocked'
                : account.status === 'expired'
                  ? 'Expired'
                  : 'Connected'}
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          Finds fresh Naukri jobs from the last 24 hours and puts them in Apply links. The agent
          never submits an application without your review.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2Icon className="size-3 animate-spin" /> Checking Naukri…
          </div>
        ) : null}

        {account && !replacing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
            <div>
              <p className="text-sm font-medium">
                {account.display_name || account.email || 'Naukri account'}
              </p>
              <p className="text-xs text-muted-foreground">
                {account.email || 'Signed in through Chrome'} · jobs land in Apply links for review
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void openWindow()}>
                <ExternalLinkIcon />
                Open Naukri
              </Button>
              <Button variant="outline" size="sm" onClick={() => setReplacing(true)}>
                Reconnect
              </Button>
              <Button variant="ghost" size="sm" onClick={() => void disconnect()}>
                <Trash2Icon />
                Disconnect
              </Button>
            </div>
          </div>
        ) : null}

        {account?.status === 'blocked' && !replacing ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Naukri blocked the last browser session. Close any other Naukri windows, then reconnect.
          </p>
        ) : null}

        {account?.status === 'expired' && !replacing ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Naukri signed this session out. Reconnect once to keep auto-applying.
          </p>
        ) : null}

        {showForm ? (
          <div className="flex flex-col gap-3">
            {error ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Naukri email" hint="Optional — only used to label the account.">
                <Input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                />
              </Field>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[11px] text-muted-foreground">
                A real Chrome window opens. Sign in there once; only the session cookies are
                stored, encrypted. The password is never kept.
              </p>
              <div className="flex gap-2">
                {replacing ? (
                  <Button variant="ghost" size="sm" onClick={() => setReplacing(false)}>
                    Cancel
                  </Button>
                ) : null}
                <Button size="sm" disabled={saving} onClick={() => void connect()}>
                  {saving ? <Loader2Icon className="animate-spin" /> : null}
                  {saving ? 'Waiting for sign-in…' : 'Connect Naukri'}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
