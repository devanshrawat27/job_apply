'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Loader2Icon, UserPlusIcon } from 'lucide-react'

import { Logo } from '@/components/logo'
import { AuthShell } from '@/components/auth-shell'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { getAccessToken, setTokens } from '@/lib/auth-storage'

export default function SignupPage() {
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
        if (!status.auth_enabled) {
          router.replace('/dashboard')
          return
        }
        if (getAccessToken()) {
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
      const tokens = await api.register(email, password)
      setTokens(tokens.access_token, tokens.refresh_token)
      router.replace('/onboarding')
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
    <AuthShell>
      <div className="mb-6 flex justify-center lg:hidden">
        <Logo href="/" />
      </div>

      <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <UserPlusIcon className="size-4 text-muted-foreground" />
          <h1 className="text-lg font-semibold tracking-tight">Create your workspace</h1>
        </div>
        <p className="mb-5 text-xs text-muted-foreground">
          Each account has its own profile, resumes, X account, jobs and history.
        </p>

          {error ? (
            <Alert variant="destructive" className="mb-4">
              <AlertTitle>Could not create the account</AlertTitle>
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
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                placeholder="At least 8 characters"
              />
            </label>
            <Button type="submit" disabled={busy} className="mt-1">
              {busy ? <Loader2Icon className="animate-spin" /> : null}
              Create account
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Already have an account?{' '}
            <Link href="/login" className="font-medium text-foreground hover:underline">
              Log in
            </Link>
          </p>
      </div>
    </AuthShell>
  )
}
