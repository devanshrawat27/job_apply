'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  Loader2Icon,
  SparklesIcon,
  UserRoundIcon,
  AtSignIcon,
  TargetIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { ConnectXForm } from '@/components/accounts/connect-x'
import { ChipInput, Field } from '@/components/profile/fields'
import {
  JOB_TITLES,
  NOT_FIT_ROLES,
  RoleChip,
  selectedRoles,
  toRolePatch,
} from '@/components/profile/roles'
import { CandidateFields, ResumeUploader } from '@/components/profile/resume'
import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import type { Account, AgentSettings, Profile } from '@/lib/types'
import { cn } from '@/lib/utils'

const STEPS = [
  { label: 'Resume', icon: UserRoundIcon },
  { label: 'Job search', icon: TargetIcon },
  { label: 'Connect X', icon: AtSignIcon },
  { label: 'Review', icon: CheckCircle2Icon },
] as const

const SKILL_SUGGESTIONS = [
  'React',
  'TypeScript',
  'Node.js',
  'Python',
  'FastAPI',
  'PostgreSQL',
  'Docker',
  'AWS',
]

export default function OnboardingPage() {
  const router = useRouter()

  const [step, setStep] = useState(0)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [settings, setSettings] = useState<AgentSettings | null>(null)

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showManual, setShowManual] = useState(false)
  const [customRole, setCustomRole] = useState('')

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const [prof, accounts, setts] = await Promise.all([
          api.getProfile(),
          api.accounts(),
          api.getSettings(),
        ])
        if (!active) return
        setProfile(prof)
        setAccount(accounts[0] ?? null)
        setSettings(setts)
        if (prof.onboarding_completed && accounts.length > 0) router.replace('/dashboard')
      } catch (cause) {
        if (active) setError((cause as Error).message)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [router])

  function patchProfile(patch: Partial<Profile>) {
    setProfile((current) => (current ? { ...current, ...patch } : current))
  }

  async function saveProfile(nextStep: number) {
    if (!profile) return
    if (step === 0 && !profile.full_name.trim()) {
      setError('Add your name so the DMs can introduce you.')
      return
    }
    if (step === 1 && !(profile.job_title || '').trim()) {
      setError('Pick or type the job title you want the agent to search for.')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const saved = await api.saveProfile(profile)
      setProfile(saved)
      setStep(nextStep)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function finish() {
    if (!profile || !account) return
    setSaving(true)
    setError(null)
    try {
      await api.saveProfile({ ...profile, onboarding_completed: true })
      await api.saveSettings({
        use_public_reply: settings?.use_public_reply ?? true,
        send_dms: settings?.send_dms ?? true,
        follow_when_needed: settings?.follow_when_needed ?? true,
        enabled: true,
      })
      toast.success('You are all set', { description: 'The agent starts with the next scan.' })
      router.push('/dashboard')
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-16">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </main>
    )
  }

  if (!profile || !settings) {
    return (
      <main className="mx-auto w-full max-w-3xl px-6 py-16">
        <Alert variant="destructive">
          <AlertTitle>Could not load your setup</AlertTitle>
          <AlertDescription>
            {error ?? 'Is the backend running on http://localhost:8000?'}
          </AlertDescription>
        </Alert>
      </main>
    )
  }

  const roles = selectedRoles(profile)
  const avoid = profile.avoid || []

  function toggleRole(title: string) {
    const next = roles.includes(title)
      ? roles.filter((role) => role !== title)
      : [...roles, title]
    patchProfile(toRolePatch(next))
  }

  function addRole(raw: string) {
    const value = raw.trim()
    if (!value) return
    if (!roles.some((role) => role.toLowerCase() === value.toLowerCase())) {
      patchProfile(toRolePatch([...roles, value]))
    }
    setCustomRole('')
  }

  function toggleAvoid(value: string) {
    const next = avoid.includes(value)
      ? avoid.filter((term) => term !== value)
      : [...avoid, value]
    patchProfile({ avoid: next })
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">
      <header className="flex items-center justify-between">
        <Logo href="/onboarding" />
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="hidden sm:inline-flex">
            4 quick steps
          </Badge>
          <ThemeToggle />
        </div>
      </header>

      {/* progress */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Setup</span>
          <span>
            Step {step + 1} of {STEPS.length}
          </span>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {STEPS.map((item, index) => {
            const Icon = item.icon
            return (
              <div key={item.label} className="flex flex-col gap-1.5">
                <div
                  className={cn(
                    'h-1 rounded-full transition-colors',
                    index <= step ? 'bg-foreground' : 'bg-muted',
                  )}
                />
                <span
                  className={cn(
                    'flex items-center gap-1 text-[11px]',
                    index === step ? 'font-medium text-foreground' : 'text-muted-foreground',
                  )}
                >
                  <Icon className="size-3" />
                  {item.label}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Something needs attention</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {step === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Start with your resume</CardTitle>
            <CardDescription>
              Upload it once — we pull out your contact details, links, skills and
              experience. You only confirm.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <ResumeUploader profile={profile} onUploaded={(p) => setProfile(p)} />

            {!profile.resume_filename && !showManual ? (
              <button
                type="button"
                className="text-xs text-muted-foreground underline-offset-4 hover:underline"
                onClick={() => setShowManual(true)}
              >
                I would rather type my details
              </button>
            ) : null}

            {profile.resume_filename || showManual ? (
              <div className="flex flex-col gap-5">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <SparklesIcon className="size-3.5 text-emerald-500" />
                  Check what we extracted. Edit anything that looks off.
                </div>

                <CandidateFields profile={profile} onChange={patchProfile} />

                <ChipInput
                  label="Skills"
                  values={profile.skills}
                  onChange={(skills) => patchProfile({ skills })}
                  suggestions={SKILL_SUGGESTIONS}
                  hint="Used to score posts and to write your DM."
                />
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <span className="text-[11px] text-muted-foreground">
                Step 1 of 4 · takes about 30 seconds
              </span>
              <Button onClick={() => void saveProfile(1)} disabled={saving}>
                {saving ? <Loader2Icon className="animate-spin" /> : null}
                Continue
                <ArrowRightIcon />
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === 1 ? (
        <Card>
          <CardHeader>
            <CardTitle>Which roles should the agent hunt for?</CardTitle>
            <CardDescription>
              Pick one or more. The first is the primary focus, but the agent also
              watches closely related roles your resume fits.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">Job titles</p>
                <Badge variant={(profile.domain || 'tech') === 'tech' ? 'info' : 'secondary'}>
                  {(profile.domain || 'tech') === 'tech' ? 'looks like a tech resume' : 'looks like a non-tech resume'}
                </Badge>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {JOB_TITLES.map((title) => (
                  <RoleChip
                    key={title}
                    label={title}
                    active={roles.includes(title)}
                    badge={roles[0] === title ? 'primary' : undefined}
                    onClick={() => toggleRole(title)}
                  />
                ))}
              </div>

              <Input
                value={customRole}
                onChange={(e) => setCustomRole(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    addRole(customRole)
                  }
                }}
                placeholder="Role not listed? Type it and press Enter"
                className="mt-1"
              />
            </div>

            {roles.length > 0 ? (
              <p className="text-[11px] text-muted-foreground">
                Selected: <span className="text-foreground">{roles.join(', ')}</span>. The agent
                also searches adjacent roles your skills support, and never searches anything
                you mark as “not a fit” below.
              </p>
            ) : (
              <p className="text-[11px] text-amber-600 dark:text-amber-400">
                Pick at least one role.
              </p>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Experience level" hint="Only two buckets: fresher or experienced.">
                <select
                  value={profile.seniority || 'fresher'}
                  onChange={(e) => patchProfile({ seniority: e.target.value })}
                  className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none dark:bg-input/30"
                >
                  <option value="fresher">Fresher</option>
                  <option value="experienced">Experienced</option>
                </select>
              </Field>

              <Field label="Resume type" hint="Non-tech resumes never get engineering searches.">
                <select
                  value={profile.domain || 'tech'}
                  onChange={(e) => patchProfile({ domain: e.target.value as Profile['domain'] })}
                  className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none dark:bg-input/30"
                >
                  <option value="tech">Tech</option>
                  <option value="non-tech">Non-tech</option>
                </select>
              </Field>
            </div>

            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted-foreground">Which roles are not a fit?</p>
              <p className="text-[11px] text-muted-foreground">
                Optional. Anything you pick here is skipped before drafting.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {NOT_FIT_ROLES.map((item) => (
                  <RoleChip
                    key={item.value}
                    label={item.label}
                    active={avoid.includes(item.value)}
                    onClick={() => toggleAvoid(item.value)}
                  />
                ))}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Minimum salary (optional)">
                <Input
                  value={profile.min_salary}
                  onChange={(e) => patchProfile({ min_salary: e.target.value })}
                  placeholder="e.g. 12 LPA"
                />
              </Field>
            </div>

            <div className="rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
              The agent learns search keywords on its own: it tries new ones in the
              background, keeps the ones that bring relevant posts, and drops the rest.
              Location is never used as a filter.
            </div>

            <div className="rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
              Location is not used as a filter. The agent only compares it when a post
              explicitly demands on-site work somewhere else.
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <Button variant="ghost" onClick={() => setStep(0)}>
                <ArrowLeftIcon />
                Back
              </Button>
              <Button onClick={() => void saveProfile(2)} disabled={saving || roles.length === 0}>
                {saving ? <Loader2Icon className="animate-spin" /> : null}
                Continue
                <ArrowRightIcon />
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === 2 ? (
        <Card>
          <CardHeader>
            <CardTitle>Connect your X account</CardTitle>
            <CardDescription>
              The agent works as this account. A browser window opens so you can clear any
              CAPTCHA or 2FA prompt.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {account ? (
              <div className="flex items-center justify-between rounded-xl border border-border bg-muted/20 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">@{account.username}</p>
                  <p className="text-xs text-muted-foreground">
                    Session saved · {account.has_dm_passcode ? 'DM passcode saved' : 'no DM passcode'}
                  </p>
                </div>
                <Badge variant="success" className="gap-1.5">
                  <CheckCircle2Icon className="size-3" />
                  Connected
                </Badge>
              </div>
            ) : (
              <ConnectXForm
                onConnected={(next) => setAccount(next)}
                allowReply={settings.use_public_reply}
                allowDm={settings.send_dms}
                allowFollow={settings.follow_when_needed}
                onAllowReply={(value) => setSettings({ ...settings, use_public_reply: value })}
                onAllowDm={(value) => setSettings({ ...settings, send_dms: value })}
                onAllowFollow={(value) => setSettings({ ...settings, follow_when_needed: value })}
              />
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <Button variant="ghost" onClick={() => setStep(1)}>
                <ArrowLeftIcon />
                Back
              </Button>
              <Button onClick={() => setStep(3)} disabled={!account}>
                Continue
                <ArrowRightIcon />
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === 3 ? (
        <Card>
          <CardHeader>
            <CardTitle>Ready to go</CardTitle>
            <CardDescription>One last look before the agent starts.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <SummaryRow
              label="Profile"
              value={profile.full_name || '—'}
              hint={
                [
                  profile.current_role || null,
                  profile.email || null,
                ]
                  .filter(Boolean)
                  .join(' · ') || 'Add a current role later'
              }
            />
            <SummaryRow
              label="Job titles"
              value={roles.join(', ') || '—'}
              hint={[
                roles.length > 1 ? `${roles[0]} is the primary focus` : 'primary focus',
                profile.domain === 'non-tech' ? 'non-tech resume' : 'tech resume',
                profile.seniority,
              ].join(' · ')}
            />
            <SummaryRow
              label="X account"
              value={account ? `@${account.username}` : 'Not connected'}
              hint={
                [
                  settings.use_public_reply ? 'public reply' : 'no public reply',
                  settings.send_dms ? 'DM' : 'no DM',
                ].join(' · ')
              }
            />
            <SummaryRow
              label="Resume"
              value={profile.resume_filename || 'Typed manually'}
              hint={`${profile.skills.length} skills tracked`}
            />

            <div className="rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
              The agent only auto-sends when it is confident about the match. Everything else
              waits in <span className="font-medium text-foreground">Approvals</span>. You can
              pause it any time from Settings.
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <Button variant="ghost" onClick={() => setStep(2)}>
                <ArrowLeftIcon />
                Back
              </Button>
              <Button onClick={() => void finish()} disabled={saving}>
                {saving ? <Loader2Icon className="animate-spin" /> : <CheckCircle2Icon />}
                Finish setup
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </main>
  )
}

function SummaryRow({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/20 px-4 py-3">
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium">{value}</p>
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      </div>
      <CheckCircle2Icon className="mt-1 size-4 shrink-0 text-emerald-500" />
    </div>
  )
}
