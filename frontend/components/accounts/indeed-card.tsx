'use client'

import { useEffect, useState } from 'react'
import {
  CheckCircle2Icon,
  ExternalLinkIcon,
  Loader2Icon,
  SearchIcon,
  Trash2Icon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/profile/fields'
import { api } from '@/lib/api'
import type { IndeedAccount } from '@/lib/types'

export function IndeedCard() {
  const [account, setAccount] = useState<IndeedAccount | null>(null)
  const [loading, setLoading] = useState(true)
  const [replacing, setReplacing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')

  async function load() {
    try {
      setAccount(await api.indeedAccount())
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
    toast.info('A Chrome window is opening. Sign in to Indeed there — waiting up to 5 minutes.')
    try {
      const saved = await api.connectIndeed(email.trim())
      setAccount(saved)
      setReplacing(false)
      toast.success('Indeed connected', {
        description: 'Quick Apply jobs will now wait in Approvals for your review.',
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
      await api.disconnectIndeed(account.id)
      setAccount(null)
      toast.success('Indeed disconnected')
    } catch (cause) {
      toast.error((cause as Error).message)
    }
  }

  async function openWindow() {
    try {
      await api.indeedWindow()
      toast.success('Indeed window opened')
    } catch (cause) {
      toast.error((cause as Error).message)
    }
  }

  const showForm = !account || replacing

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SearchIcon className="size-4 text-blue-500" />
          Indeed
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
          Finds fresh Indeed India jobs for the last 24 hours. Direct Quick Apply jobs land in
          Approvals; company-site jobs land in Apply links.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2Icon className="size-3 animate-spin" /> Checking Indeed…
          </div>
        ) : null}

        {account && !replacing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
            <div>
              <p className="text-sm font-medium">
                {account.display_name || account.email || 'Indeed account'}
              </p>
              <p className="text-xs text-muted-foreground">
                {account.email || 'Signed in through Chrome'} · Quick Apply needs this session
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => void openWindow()}>
                <ExternalLinkIcon />
                Open Indeed
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

        {account && !replacing ? (
          <p className="text-[11px] text-muted-foreground">
            Search works without a login. A one-time Indeed sign-in is needed before the agent can
            use Quick Apply. Indeed may still ask screening questions — those wait for you.
          </p>
        ) : null}

        {account?.status === 'blocked' && !replacing ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Indeed blocked the last browser session. Complete its verification in the Indeed
            window, then reconnect.
          </p>
        ) : null}

        {account?.status === 'expired' && !replacing ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            Indeed signed this session out. Reconnect once to keep Quick Apply working.
          </p>
        ) : null}

        {showForm ? (
          <div className="flex flex-col gap-3">
            {error ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            ) : null}
            <Field label="Indeed email (optional)">
              <Input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => void connect()} disabled={saving}>
                {saving ? <Loader2Icon className="animate-spin" /> : <ExternalLinkIcon />}
                Open Indeed login
              </Button>
              {replacing ? (
                <Button variant="ghost" onClick={() => setReplacing(false)}>
                  Cancel
                </Button>
              ) : null}
            </div>
            <p className="text-[11px] text-muted-foreground">
              A Chrome window opens at Indeed. Sign in there; the password never reaches JobPilot.
              Only the resulting session cookies are stored, encrypted.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
