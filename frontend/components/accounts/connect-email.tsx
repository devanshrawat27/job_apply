'use client'

import { useEffect, useState } from 'react'
import { CheckCircle2Icon, Loader2Icon, MailIcon, PencilIcon, Trash2Icon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { EmailAccount } from '@/lib/types'

const EMPTY = {
  host: 'smtp.gmail.com',
  port: 587,
  username: '',
  password: '',
  from_address: '',
  starttls: true,
}

export function ConnectEmail({ onSaved }: { onSaved?: () => void }) {
  const [status, setStatus] = useState<EmailAccount | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [form, setForm] = useState({ ...EMPTY })

  async function load() {
    try {
      const next = await api.emailAccount()
      setStatus(next)
      setForm({
        host: next.host || 'smtp.gmail.com',
        port: next.port || 587,
        username: next.username || '',
        password: '',
        from_address: next.from_address || '',
        starttls: next.starttls ?? true,
      })
      setEditing(!next.configured || next.source === 'env')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function save() {
    if (!form.username.trim() || !form.password.trim()) {
      toast.error('Enter your email address and app password')
      return
    }
    setBusy('save')
    try {
      await api.saveEmailAccount({
        host: form.host.trim() || 'smtp.gmail.com',
        port: Number(form.port) || 587,
        username: form.username.trim(),
        password: form.password.trim(),
        from_address: form.from_address.trim(),
        starttls: form.starttls,
      })
      await load()
      onSaved?.()
      const check = await api.testEmailAccount()
      if (check.ok) {
        toast.success('Email connected')
      } else {
        toast.error(check.error || 'Gmail rejected the login')
      }
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function disconnect() {
    setBusy('delete')
    try {
      await api.deleteEmailAccount()
      toast.success('Email disconnected')
      await load()
      onSaved?.()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2Icon className="size-3 animate-spin" />
        Checking email…
      </div>
    )
  }

  if (status?.configured && status.source === 'workspace' && !editing) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
        <div className="flex items-start gap-2">
          <CheckCircle2Icon className="mt-0.5 size-4 text-emerald-500" />
          <div>
            <p className="text-sm font-medium">{status.from_address || status.username}</p>
            <p className="text-[11px] text-muted-foreground">Connected</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => setEditing(true)}>
            <PencilIcon />
            Edit
          </Button>
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void disconnect()}>
            <Trash2Icon />
            Disconnect
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
        Email address
        <Input
          type="email"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          placeholder="you@gmail.com"
        />
      </label>

      <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
        App password
        <Input
          type="password"
          autoComplete="off"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          placeholder="16-character app password"
        />
      </label>

      <details className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-[11px] text-muted-foreground">
          Other email provider
        </summary>
        <div className="flex flex-col gap-3 pt-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              SMTP host
              <Input
                value={form.host}
                onChange={(e) => setForm({ ...form, host: e.target.value })}
                placeholder="smtp.gmail.com"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Port
              <Input
                type="number"
                value={form.port}
                onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
              />
            </label>
          </div>
          <label className="flex cursor-pointer items-start gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={form.starttls}
              onChange={(e) => setForm({ ...form, starttls: e.target.checked })}
              className="mt-0.5 size-4 accent-foreground"
            />
            STARTTLS (port 587). Turn off for SSL-only providers.
          </label>
        </div>
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy !== null} onClick={() => void save()}>
          {busy === 'save' ? <Loader2Icon className="animate-spin" /> : <MailIcon />}
          Connect email
        </Button>
        {status?.configured ? (
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => setEditing(false)}>
            Cancel
          </Button>
        ) : null}
        <span className="text-[11px] text-muted-foreground">
          Gmail: create an App Password in Google Account → Security.
        </span>
      </div>
    </div>
  )
}
