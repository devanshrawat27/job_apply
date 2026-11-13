'use client'

import { useEffect, useState } from 'react'
import {
  AtSignIcon,
  CheckCircle2Icon,
  Loader2Icon,
  MailIcon,
  PinIcon,
  SaveIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
} from 'lucide-react'
import { toast } from 'sonner'

import { ConnectXForm } from '@/components/accounts/connect-x'
import { PageHeader } from '@/components/page-header'
import { ChipInput, Field } from '@/components/profile/fields'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Separator, Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import { useWorkspace } from '@/lib/use-workspace'
import type { AgentSettings, KeywordsSnapshot, LLMKey } from '@/lib/types'

function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  hint?: string
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 shrink-0 accent-foreground"
      />
      <span>
        <span className="block text-sm">{label}</span>
        {hint ? <span className="block text-[11px] text-muted-foreground">{hint}</span> : null}
      </span>
    </label>
  )
}

export default function SettingsPage() {
  const { settings, account, loading, error, reload } = useWorkspace()
  const [form, setForm] = useState<AgentSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [replacing, setReplacing] = useState(false)
  const [keywords, setKeywords] = useState<KeywordsSnapshot | null>(null)
  const [emailReady, setEmailReady] = useState<boolean | null>(null)
  const [llmReady, setLlmReady] = useState<boolean | null>(null)
  const [passcodeDraft, setPasscodeDraft] = useState('')
  const [savingPasscode, setSavingPasscode] = useState(false)
  const [llmKeys, setLlmKeys] = useState<LLMKey[]>([])
  const [llmForm, setLlmForm] = useState({
    label: 'ChatGPT',
    model: 'gpt-4o-mini',
    api_key: '',
    base_url: 'https://api.openai.com/v1',
  })
  const [savingKey, setSavingKey] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [chatgpt, setChatgpt] = useState<{ connected: boolean; enabled: boolean } | null>(null)
  const [chatgptAccount, setChatgptAccount] = useState<{
    email: string
    name: string
    plan: string
  } | null>(null)
  const [connecting, setConnecting] = useState(false)

  useEffect(() => {
    if (settings) setForm(settings)
  }, [settings])

  useEffect(() => {
    api
      .keywords()
      .then(setKeywords)
      .catch(() => setKeywords(null))
    api
      .llmKeys()
      .then((keys) => {
        setLlmKeys(keys)
        setLlmReady(keys.some((key) => key.enabled) ? true : null)
      })
      .catch(() => setLlmKeys([]))
    api
      .chatgptStatus()
      .then((status) => {
        setChatgpt(status)
        if (status.connected) {
          api
            .chatgptAccount()
            .then(setChatgptAccount)
            .catch(() => setChatgptAccount(null))
        }
      })
      .catch(() => setChatgpt(null))
    api
      .health()
      .then((health) => {
        setEmailReady(health.email_configured)
        setLlmReady((current) => current ?? health.llm_configured)
      })
      .catch(() => setEmailReady(null))
  }, [])

  function patch(value: Partial<AgentSettings>) {
    setForm((current) => (current ? { ...current, ...value } : current))
  }

  async function save() {
    if (!form) return
    setSaving(true)
    try {
      await api.saveSettings(form)
      await reload()
      toast.success('Settings saved')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function disconnect() {
    if (!account) return
    try {
      await api.disconnect(account.id)
      setReplacing(true)
      await reload()
      toast.success('Account disconnected')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function savePasscode(value: string | null) {
    if (!account) return
    setSavingPasscode(true)
    try {
      await api.setDmPasscode(account.id, value)
      setPasscodeDraft('')
      await reload()
      toast.success(value ? 'Chat passcode saved' : 'Chat passcode cleared')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSavingPasscode(false)
    }
  }

  async function saveLlmKey() {
    if (llmForm.api_key.trim().length < 8) {
      toast.error('Paste the API key first')
      return
    }
    setSavingKey(true)
    try {
      await api.saveLLMKey({
        label: llmForm.label.trim() || 'ChatGPT',
        provider: 'openai',
        api_key: llmForm.api_key.trim(),
        base_url: llmForm.base_url.trim() || 'https://api.openai.com/v1',
        model: llmForm.model.trim() || 'gpt-4o-mini',
      })
      const keys = await api.llmKeys()
      setLlmKeys(keys)
      setLlmReady(true)
      setLlmForm((current) => ({ ...current, api_key: '' }))
      toast.success('ChatGPT key saved (encrypted)')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSavingKey(false)
    }
  }

  async function testLlmKey(id: number) {
    setTestingId(id)
    try {
      const result = await api.testLLMKey(id)
      toast.success(`Key works (${result.model})`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setTestingId(null)
    }
  }

  async function togglePin(keyword: string, pinned: boolean) {
    try {
      await api.pinKeyword(keyword, pinned)
      const snapshot = await api.keywords()
      setKeywords(snapshot)
      toast.success(pinned ? `Pinned “${keyword}”` : `Unpinned “${keyword}”`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function removeLlmKey(id: number) {    try {
      await api.deleteLLMKey(id)
      const keys = await api.llmKeys()
      setLlmKeys(keys)
      if (!keys.length) setLlmReady(false)
      toast.success('Key removed')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  async function connectChatgpt() {
    setConnecting(true)
    toast.info('Chromium is opening — log in to ChatGPT in that window (waiting up to 5 minutes).')
    try {
      await api.connectChatgpt()
      setChatgpt({ connected: true, enabled: true })
      patch({ chatgpt_browser_enabled: true })
      const info = await api.chatgptAccount().catch(() => null)
      setChatgptAccount(info)
      toast.success('ChatGPT connected')
    } catch (err) {
      toast.error((err as Error).message)
      const status = await api.chatgptStatus().catch(() => null)
      if (status) setChatgpt(status)
    } finally {
      setConnecting(false)
    }
  }

  async function disconnectChatgpt() {
    try {
      await api.disconnectChatgpt()
      setChatgpt({ connected: false, enabled: false })
      setChatgptAccount(null)
      patch({ chatgpt_browser_enabled: false })
      toast.success('ChatGPT disconnected')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (loading || !form) {
    return (
      <main className="flex w-full flex-col gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </main>
    )
  }

  return (
    <main className="flex w-full flex-col gap-5">
      <PageHeader
        title="Settings"
        description="How the agent behaves, who it acts as, and the guard rails."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={form.enabled ? 'success' : 'warning'}>
              {form.enabled ? 'Agent on' : 'Agent paused'}
            </Badge>
            <Badge variant={account ? 'success' : 'warning'}>
              {account ? `@${account.username}` : 'X not connected'}
            </Badge>
            <Badge variant={chatgpt?.connected ? 'success' : 'warning'}>
              {chatgpt?.connected ? 'ChatGPT connected' : 'No ChatGPT'}
            </Badge>
            <Button size="sm" onClick={() => void save()} disabled={saving}>
              {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
              Save settings
            </Button>
          </div>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load settings</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* ------------------------------------------------------- agent */}
      <Card>
        <CardHeader>
          <CardTitle>Agent</CardTitle>
          <CardDescription>Scan frequency and the auto-send bar.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <Toggle
            checked={form.enabled}
            onChange={(enabled) => patch({ enabled })}
            label="Run the agent on a schedule"
            hint="Off means the agent only runs when you press Scan now."
          />

          <Separator />

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Scan every (minutes)">
              <Input
                type="number"
                min={5}
                value={form.scan_interval_minutes}
                onChange={(e) => patch({ scan_interval_minutes: Number(e.target.value) })}
              />
            </Field>
            <Field label="Only posts newer than (hours)">
              <Input
                type="number"
                min={1}
                value={form.lookback_hours}
                onChange={(e) => patch({ lookback_hours: Number(e.target.value) })}
              />
            </Field>
            <Field label="Posts to read per query">
              <Input
                type="number"
                min={5}
                max={100}
                value={form.max_posts_per_scan}
                onChange={(e) => patch({ max_posts_per_scan: Number(e.target.value) })}
              />
            </Field>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted-foreground">Relevance threshold</span>
                <span className="text-sm font-medium tabular-nums">{form.relevance_threshold}</span>
              </div>
              <input
                type="range"
                min={30}
                max={95}
                value={form.relevance_threshold}
                onChange={(e) => patch({ relevance_threshold: Number(e.target.value) })}
                className="w-full accent-foreground"
              />
              <p className="text-[11px] text-muted-foreground">
                Posts scoring below this are skipped without drafting.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted-foreground">Auto-send confidence</span>
                <span className="text-sm font-medium tabular-nums">
                  {Math.round(form.auto_send_confidence * 100)}%
                </span>
              </div>
              <input
                type="range"
                min={50}
                max={100}
                value={Math.round(form.auto_send_confidence * 100)}
                onChange={(e) => patch({ auto_send_confidence: Number(e.target.value) / 100 })}
                className="w-full accent-foreground"
              />
              <p className="text-[11px] text-muted-foreground">
                Below this the draft waits in Approvals. Anything unsure always waits.
              </p>
            </div>
          </div>

          <Toggle
            checked={form.auto_send_enabled}
            onChange={(auto_send_enabled) => patch({ auto_send_enabled })}
            label="Auto-send when confident"
            hint="Caps and cool-down still apply."
          />
        </CardContent>
      </Card>

      {/* --------------------------------------------------- guard rails */}
      <Card>
        <CardHeader>
          <CardTitle>Guard rails</CardTitle>
          <CardDescription>Protects your account from looking like a bot.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Replies per day">
              <Input
                type="number"
                min={0}
                value={form.daily_reply_cap}
                onChange={(e) => patch({ daily_reply_cap: Number(e.target.value) })}
              />
            </Field>
            <Field label="DMs per day">
              <Input
                type="number"
                min={0}
                value={form.daily_dm_cap}
                onChange={(e) => patch({ daily_dm_cap: Number(e.target.value) })}
              />
            </Field>
            <Field label="Minutes between writes">
              <Input
                type="number"
                min={0}
                value={form.min_minutes_between_writes}
                onChange={(e) => patch({ min_minutes_between_writes: Number(e.target.value) })}
              />
            </Field>
          </div>

          <Field
            label="Quiet hours (UTC)"
            hint="No writes in this window. Format 23-7, or leave empty to disable."
          >
            <Input
              value={form.quiet_hours}
              onChange={(e) => patch({ quiet_hours: e.target.value })}
              placeholder="23-7"
            />
          </Field>

          <Separator />

          <Toggle
            checked={form.use_public_reply}
            onChange={(use_public_reply) => patch({ use_public_reply })}
            label="Post a public reply before the DM"
            hint="The reply is short and has no links."
          />
          <Toggle
            checked={form.send_dms}
            onChange={(send_dms) => patch({ send_dms })}
            label="Send a personal DM"
            hint="Requires the chat passcode you saved when connecting X."
          />
          <Toggle
            checked={form.follow_when_needed}
            onChange={(follow_when_needed) => patch({ follow_when_needed })}
            label="Follow only when X blocks the DM"
            hint="Used when X blocks a DM, and as a nudge when someone has not replied."
          />

          <details className="rounded-xl border border-border px-3 py-2">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Advanced — add your own search queries
            </summary>
            <div className="pt-3">
              <ChipInput
                label="Extra search queries"
                values={form.extra_queries}
                onChange={(extra_queries) => patch({ extra_queries })}
                placeholder="A full X search query"
                hint="Added on top of the generated queries. Use sparingly."
              />
            </div>
          </details>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------ keywords */}
      <Card>
        <CardHeader>
          <CardTitle>Search keywords</CardTitle>
          <CardDescription>
            The agent tests keywords in the background and keeps the ones that bring
            relevant posts.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              In use
            </p>
            {keywords?.active?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {keywords.active.map((item) => (
                  <button
                    key={item.keyword}
                    type="button"
                    onClick={() => void togglePin(item.keyword, !item.pinned)}
                    title={item.pinned ? 'Pinned - click to unpin' : 'Click to pin this keyword'}
                    className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-600 dark:text-emerald-400"
                  >
                    {item.pinned ? <PinIcon className="size-3" /> : null}
                    {item.keyword}
                    <span className="text-[10px] opacity-70">
                      {Math.round(item.score * 100)}%
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Nothing proven yet. Run a scan and the agent starts testing.
              </p>
            )}
          </div>

          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Being tested
            </p>
            {keywords?.testing?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {keywords.testing.map((item) => (
                  <button
                    key={item.keyword}
                    type="button"
                    onClick={() => void togglePin(item.keyword, !item.pinned)}
                    title={
                      item.pinned
                        ? 'Pinned - click to unpin'
                        : `score ${item.score} · ${item.posts_relevant}/${item.posts_seen} relevant · used ${item.uses}x`
                    }
                    className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-foreground/30"
                  >
                    {item.pinned ? <PinIcon className="size-3 text-foreground" /> : null}
                    {item.keyword}
                    <span className="text-[10px] opacity-70">
                      {item.posts_seen ? `${item.posts_relevant}/${item.posts_seen}` : 'new'}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No candidates queued.</p>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">
            Click a keyword to pin it. Pinned keywords are always searched; weak unpinned
            ones are dropped automatically.
          </p>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------ AI analyst */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SparklesIcon className="size-4" />
            AI analyst — ChatGPT
          </CardTitle>
          <CardDescription>
            ChatGPT grades your keywords and improves drafts. It never sends anything.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {llmKeys.length ? (
            <div className="flex flex-col gap-2">
              {llmKeys.map((key) => (
                <div
                  key={key.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-medium">
                      {key.label}{' '}
                      <span className="text-xs font-normal text-muted-foreground">
                        {key.masked}
                      </span>
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {key.model} · {key.base_url}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={testingId === key.id}
                      onClick={() => void testLlmKey(key.id)}
                    >
                      {testingId === key.id ? <Loader2Icon className="animate-spin" /> : null}
                      Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void removeLlmKey(key.id)}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <details
            className="rounded-xl border border-border px-3 py-2"
            open={llmKeys.length > 0}
          >
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Advanced — use an API key instead
            </summary>
            <div className="flex flex-col gap-3 pt-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Label">
                  <Input
                    value={llmForm.label}
                    onChange={(e) => setLlmForm({ ...llmForm, label: e.target.value })}
                    placeholder="ChatGPT"
                  />
                </Field>
                <Field label="Model">
                  <Input
                    value={llmForm.model}
                    onChange={(e) => setLlmForm({ ...llmForm, model: e.target.value })}
                    placeholder="gpt-4o-mini"
                  />
                </Field>
              </div>

              <Field label="API key" hint="Stored encrypted and never shown again after saving.">
                <Input
                  type="password"
                  autoComplete="off"
                  value={llmForm.api_key}
                  onChange={(e) => setLlmForm({ ...llmForm, api_key: e.target.value })}
                  placeholder="sk-..."
                />
              </Field>

              <details className="rounded-xl border border-border px-3 py-2">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Advanced — custom base URL
                </summary>
                <div className="pt-2">
                  <Field label="Base URL" hint="Use this for OpenRouter, Azure, or a local gateway.">
                    <Input
                      value={llmForm.base_url}
                      onChange={(e) => setLlmForm({ ...llmForm, base_url: e.target.value })}
                      placeholder="https://api.openai.com/v1"
                    />
                  </Field>
                </div>
              </details>

              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" disabled={savingKey} onClick={() => void saveLlmKey()}>
                  {savingKey ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
                  Save key
                </Button>
                <span className="text-[11px] text-muted-foreground">
                  Used first for drafting and the keyword review; Gemini stays as the fallback.
                </span>
              </div>
            </div>
          </details>

          <Separator />

          {chatgpt?.connected ? (
            <div className="rounded-xl border border-border bg-muted/20 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">ChatGPT (browser)</p>
                  <p className="text-[11px] text-muted-foreground">
                    {chatgptAccount
                      ? `${chatgptAccount.email}${
                          chatgptAccount.plan ? ` · ${chatgptAccount.plan} plan` : ''
                        }`
                      : 'Signed in'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={connecting}
                    onClick={() => void connectChatgpt()}
                  >
                    {connecting ? <Loader2Icon className="animate-spin" /> : null}
                    {connecting ? 'Waiting for login…' : 'Reconnect'}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void disconnectChatgpt()}>
                    Disconnect
                  </Button>
                </div>
              </div>
              <div className="mt-3">
                <Toggle
                  checked={form.chatgpt_browser_enabled}
                  onChange={(chatgpt_browser_enabled) => patch({ chatgpt_browser_enabled })}
                  label="Use ChatGPT for analysis and drafts"
                  hint="Runs in Chromium. No API key needed."
                />
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border p-3">
              <p className="text-sm font-medium">Connect ChatGPT</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Log in once in Chromium. The agent will ask ChatGPT to grade keywords and
                write better replies/DMs — no API key needed.
              </p>
              <Button
                size="sm"
                className="mt-2"
                disabled={connecting}
                onClick={() => void connectChatgpt()}
              >
                {connecting ? <Loader2Icon className="animate-spin" /> : <AtSignIcon />}
                {connecting ? 'Waiting for login…' : 'Connect ChatGPT'}
              </Button>
              <p className="mt-2 text-[11px] text-muted-foreground">
                Opens Chromium for the login; it is detected automatically (up to 5 minutes).
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ------------------------------------------------- message quality */}
      <Card>
        <CardHeader>
          <CardTitle>Message quality</CardTitle>
          <CardDescription>
            Generic drafts never get sent. The model writes the ones that do.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={llmReady || chatgpt?.connected ? 'success' : 'warning'}>
              {llmReady === null && !chatgpt
                ? 'checking…'
                : llmReady || chatgpt?.connected
                  ? 'Model connected'
                  : 'No model'}
            </Badge>
          </div>

          <p className="text-xs text-muted-foreground">
            A specific draft above your confidence bar is sent automatically. Generic or
            uncertain drafts wait in Approvals. External-link posts never get a reply or DM.
          </p>

          {!llmReady && !chatgpt?.connected ? (
            <p className="text-xs text-muted-foreground">
              Connect ChatGPT in the AI analyst card above, or add an API key there.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {/* --------------------------------------------------------- email */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MailIcon className="size-4" />
            Email applications
          </CardTitle>
          <CardDescription>
            When a post says “mail your resume to …”, the agent emails it with your resume
            attached.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Badge variant={emailReady ? 'success' : 'warning'}>
              {emailReady === null ? 'checking…' : emailReady ? 'configured' : 'not configured'}
            </Badge>
            {!emailReady ? (
              <span className="text-[11px] text-muted-foreground">
                Posts that need email will wait in Approvals.
              </span>
            ) : null}
          </div>

          <details className="rounded-xl border border-border px-3 py-2">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              Advanced — SMTP setup
            </summary>
            <div className="flex flex-col gap-2 pt-2">
              <pre className="overflow-x-auto rounded-lg border border-border bg-background p-3 font-mono text-[11px] text-muted-foreground">
{`# backend/.env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=you@gmail.com`}
              </pre>
              <p className="text-[11px] text-muted-foreground">
                Gmail uses an App Password (Google Account → Security → App passwords), not
                your normal password. Restart the backend after changing .env.
              </p>
            </div>
          </details>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------ account */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AtSignIcon className="size-4" />
            X account
          </CardTitle>
          <CardDescription>The account the agent replies and DMs from.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {account ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 px-4 py-3">
              <div>
                <p className="text-sm font-medium">@{account.username}</p>
                <p className="text-xs text-muted-foreground">
                  {account.status} · {account.has_dm_passcode ? 'DM passcode saved' : 'no DM passcode (optional)'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="success" className="gap-1.5">
                  <CheckCircle2Icon className="size-3" />
                  Connected
                </Badge>
                <Button variant="ghost" size="sm" onClick={() => void disconnect()}>
                  <Trash2Icon />
                  Disconnect
                </Button>
              </div>
            </div>
          ) : null}

          {account ? (
            <div className="rounded-xl border border-border px-4 py-3">
              <p className="text-xs font-medium text-muted-foreground">
                DM chat passcode (optional)
              </p>
              <p className="mb-2 text-[11px] text-muted-foreground">
                Leave it empty and DMs are attempted normally. Add it only if X asks for a
                passcode — the failed DM tells you.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="password"
                  autoComplete="off"
                  value={passcodeDraft}
                  onChange={(e) => setPasscodeDraft(e.target.value)}
                  placeholder={account.has_dm_passcode ? 'Saved — type to replace' : 'Not set'}
                  className="max-w-xs"
                />
                <Button
                  variant="outline"
                  size="sm"
                  disabled={savingPasscode || passcodeDraft.trim().length === 0}
                  onClick={() => void savePasscode(passcodeDraft.trim())}
                >
                  {savingPasscode ? <Loader2Icon className="animate-spin" /> : null}
                  Save
                </Button>
                {account.has_dm_passcode ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={savingPasscode}
                    onClick={() => void savePasscode(null)}
                  >
                    Clear
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          {replacing || !account ? (
            <ConnectXForm
              onConnected={async () => {
                setReplacing(false)
                await reload()
              }}
              allowReply={form.use_public_reply}
              allowDm={form.send_dms}
              allowFollow={form.follow_when_needed}
              onAllowReply={(value) => patch({ use_public_reply: value })}
              onAllowDm={(value) => patch({ send_dms: value })}
              onAllowFollow={(value) => patch({ follow_when_needed: value })}
              submitLabel={account ? 'Reconnect account' : 'Connect account'}
            />
          ) : (
            <Button variant="outline" size="sm" className="self-start" onClick={() => setReplacing(true)}>
              Replace / reconnect
            </Button>
          )}

          <div className="flex items-start gap-2 rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
            <ShieldCheckIcon className="mt-0.5 size-3.5 shrink-0" />
            <p>
              Session cookies are stored encrypted and never returned by the API. The password
              only ever goes into X's own login form.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
          Save settings
        </Button>
      </div>
    </main>
  )
}
