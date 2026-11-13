'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Loader2Icon, LockKeyholeIcon } from 'lucide-react'

import { Logo } from '@/components/logo'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { getAccessToken, setTokens } from '@/lib/auth-storage'

export default function LoginPage() {
  const router = useRouter()
  const [checking, setChecking] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const status = await api.authStatus()
        if (!active) return
        if (!status.auth_enabled || getAccessToken()) {
          router.replace('/dashboard')
          return
        }
      } catch {
        if (active) setError('Backend is not reachable. Is it running?')
      } finally {
        if (active) setChecking(false)
      }
    })()
    return () => {
      active = false
    }
  }, [router])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const tokens = await api.login(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)
      router.replace('/dashboard')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (checking) {
    return (
      <main className="grid min-h-screen place-items-center">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2Icon className="size-4 animate-spin" />
          Starting JobPilot…
        </div>
      </main>
    )
  }

  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Logo href="/" />
        </div>

        <div className="rounded-2xl border border-border bg-card p-6">
          <div className="mb-4 flex items-center gap-2">
            <LockKeyholeIcon className="size-4 text-muted-foreground" />
            <h1 className="text-lg font-semibold tracking-tight">Log in to JobPilot</h1>
          </div>

          {error ? (
            <Alert variant="destructive" className="mb-4">
              <AlertTitle>Could not log in</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Email
              <Input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Password
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="Your password"
              />
            </label>
            <Button type="submit" disabled={busy} className="mt-1">
              {busy ? <Loader2Icon className="animate-spin" /> : null}
              Log in
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            New here?{' '}
            <Link href="/signup" className="font-medium text-foreground hover:underline">
              Create a workspace
            </Link>
          </p>
        </div>
      </div>
    </main>
  )
}
