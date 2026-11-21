'use client'

import { useEffect, useState } from 'react'
import { CheckCircle2Icon, LinkedinIcon, Loader2Icon, Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Field } from '@/components/profile/fields'
import { api } from '@/lib/api'
import type { LinkedInAccount } from '@/lib/types'

export function LinkedInCard() {
  const [account, setAccount] = useState<LinkedInAccount | null>(null)
  const [loading, setLoading] = useState(true)
  const [replacing, setReplacing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')

  async function load() {
    try {
      setAccount(await api.linkedinAccount())
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
    if (!email.trim() || !password) {
      setError('Enter your LinkedIn email and password.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const saved = await api.connectLinkedIn({
        email: email.trim(),
        password,
        verification_code: code.trim() || undefined,
      })
      setAccount(saved)
      setPassword('')
      setCode('')
      setReplacing(false)
      toast.success('LinkedIn connected', {
        description: 'The agent can now read individual hiring posts.',
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
      await api.disconnectLinkedIn(account.id)
      setAccount(null)
      toast.success('LinkedIn disconnected')
    } catch (cause) {
      toast.error((cause as Error).message)
    }
  }

  const showForm = !account || replacing

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LinkedinIcon className="size-4 text-sky-600" />
          LinkedIn
          {account ? (
            <Badge variant={account.status === 'expired' ? 'destructive' : 'success'} className="ml-1 gap-1">
              {account.status === 'expired' ? null : <CheckCircle2Icon className="size-3" />}
              {account.status === 'expired' ? 'Session expired' : 'Connected'}
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          Read hiring posts by individual recruiters and founders. The agent never posts,
          comments or sends connection requests.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2Icon className="size-3 animate-spin" /> Checking LinkedIn…
          </div>
        ) : null}

        {account && !replacing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
            <div>
              <p className="text-sm font-medium">
                {account.display_name || account.vanity_name || account.email}
              </p>
              <p className="text-xs text-muted-foreground">{account.email}</p>
            </div>
            <div className="flex items-center gap-2">
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

        {account?.status === 'expired' && !replacing ? (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            LinkedIn logged this session out. Reconnect to keep reading hiring posts.
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
              <Field label="LinkedIn email" hint="The account the agent reads posts with.">
                <Input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                />
              </Field>
              <Field label="Password" hint="Used once to sign in. Not stored.">
                <Input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="LinkedIn password"
                />
              </Field>
              <Field
                label="Verification code"
                hint="Only if LinkedIn asks for an email or SMS code."
              >
                <Input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  placeholder="Optional"
                />
              </Field>
            </div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] text-muted-foreground">
                The password is never stored. Only the resulting session cookies are saved,
                encrypted.
              </p>
              <div className="flex gap-2">
                {replacing ? (
                  <Button variant="ghost" size="sm" onClick={() => setReplacing(false)}>
                    Cancel
                  </Button>
                ) : null}
                <Button size="sm" disabled={saving} onClick={() => void connect()}>
                  {saving ? <Loader2Icon className="animate-spin" /> : null}
                  {saving ? 'Opening LinkedIn…' : 'Connect LinkedIn'}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
