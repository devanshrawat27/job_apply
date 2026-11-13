'use client'

import { useEffect, useState } from 'react'
import { GithubIcon, Loader2Icon, RefreshCwIcon, SaveIcon, SparklesIcon } from 'lucide-react'
import { toast } from 'sonner'

import { ChipInput, Field } from '@/components/profile/fields'
import {
  JOB_TITLES,
  NOT_FIT_ROLES,
  RoleChip,
  selectedRoles,
  toRolePatch,
} from '@/components/profile/roles'
import { CandidateFields } from '@/components/profile/resume'
import { ResumeManager } from '@/components/profile/resume-manager'
import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import { useWorkspace } from '@/lib/use-workspace'
import { timeAgo } from '@/lib/utils'
import type { Profile } from '@/lib/types'

export default function ProfilePage() {
  const { profile, loading, error, reload } = useWorkspace()
  const [form, setForm] = useState<Profile | null>(null)
  const [saving, setSaving] = useState(false)
  const [githubSyncing, setGithubSyncing] = useState(false)
  const [customRole, setCustomRole] = useState('')

  useEffect(() => {
    if (profile) setForm(profile)
  }, [profile])

  function patch(patchValue: Partial<Profile>) {
    setForm((current) => (current ? { ...current, ...patchValue } : current))
  }

  const roles = form ? selectedRoles(form) : []
  const avoid = form?.avoid || []

  function toggleRole(title: string) {
    if (!form) return
    const next = roles.includes(title) ? roles.filter((role) => role !== title) : [...roles, title]
    patch(toRolePatch(next))
  }

  function addRole(raw: string) {
    const value = raw.trim()
    if (!value) return
    if (!roles.some((role) => role.toLowerCase() === value.toLowerCase())) {
      patch(toRolePatch([...roles, value]))
    }
    setCustomRole('')
  }

  function toggleAvoid(value: string) {
    if (!form) return
    const next = avoid.includes(value) ? avoid.filter((term) => term !== value) : [...avoid, value]
    patch({ avoid: next })
  }

  async function save() {
    if (!form) return
    setSaving(true)
    try {
      await api.saveProfile(form)
      await reload()
      toast.success('Profile saved')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function syncGithub() {
    setGithubSyncing(true)
    try {
      await api.syncGithub()
      await reload()
      toast.success('GitHub data refreshed')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setGithubSyncing(false)
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
        title="Profile"
        description="Your resume and the roles the agent searches for. Change anything, any time."
        actions={
          <Button size="sm" onClick={() => void save()} disabled={saving}>
            {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
            Save changes
          </Button>
        }
      />

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load your profile</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Resumes</CardTitle>
          <CardDescription>
            Keep multiple. The agent picks the most relevant one for each post and attaches it
            when it emails.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ResumeManager
            onChanged={async () => {
              const next = await api.getProfile()
              setForm(next)
              await reload()
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Basic info</CardTitle>
          <CardDescription>Everything the agent uses to introduce you in a DM.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <CandidateFields profile={form} onChange={patch} />

          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <SparklesIcon className="size-3.5 text-emerald-500" />
            Extracted from your resume — edit freely.
          </div>

          <ChipInput
            label="Skills"
            values={form.skills}
            onChange={(skills) => patch({ skills })}
            suggestions={['React', 'TypeScript', 'Node.js', 'Python', 'FastAPI', 'Docker', 'AWS']}
            hint="Used to score posts and to write your DM."
          />

          <Field
            label="DM pitch (optional)"
            hint="Leave it empty and the agent writes the proof line from your role and skills."
          >
            <Textarea
              value={form.pitch}
              onChange={(e) => patch({ pitch: e.target.value })}
              placeholder="e.g. I build production web apps with React and FastAPI."
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Job search</CardTitle>
          <CardDescription>These become the X search queries.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted-foreground">Job titles</p>
              <Badge variant={form.domain === 'tech' ? 'info' : 'secondary'}>
                {form.domain === 'tech' ? 'tech resume' : 'non-tech resume'}
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
            <p className="text-[11px] text-muted-foreground">
              {roles.length
                ? `Primary: ${roles[0]}. The agent also searches adjacent roles your skills fit.`
                : 'Pick at least one role.'}
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Experience level" hint="Only two buckets: fresher or experienced.">
              <select
                value={form.seniority || 'fresher'}
                onChange={(e) => patch({ seniority: e.target.value })}
                className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none dark:bg-input/30"
              >
                <option value="fresher">Fresher</option>
                <option value="experienced">Experienced</option>
              </select>
            </Field>
            <Field label="Resume type" hint="Non-tech resumes never get engineering searches.">
              <select
                value={form.domain || 'tech'}
                onChange={(e) => patch({ domain: e.target.value as Profile['domain'] })}
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
              Anything you pick here is skipped before drafting.
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
                value={form.min_salary}
                onChange={(e) => patch({ min_salary: e.target.value })}
                placeholder="e.g. 12 LPA"
              />
            </Field>
          </div>

          <div className="rounded-xl border border-border bg-muted/20 p-3 text-[11px] text-muted-foreground">
            Search keywords are managed by the agent: it tests new ones, keeps the ones that
            bring relevant posts, and drops the rest. Location is never a filter.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GithubIcon className="size-4" />
            GitHub profile
          </CardTitle>
          <CardDescription>
            Your public repos and languages are used to write concrete messages and match
            jobs better.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {form.links?.github ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">
                    @{form.github_username || 'not synced yet'}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {form.github_data?.public_repos ?? 0} repos ·{' '}
                    {form.github_data?.stars ?? 0} stars
                    {form.github_data?.active_days_ago != null
                      ? ` · active ${form.github_data.active_days_ago}d ago`
                      : ''}
                    {form.github_synced_at
                      ? ` · updated ${timeAgo(form.github_synced_at)}`
                      : ''}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={githubSyncing}
                  onClick={() => void syncGithub()}
                >
                  {githubSyncing ? (
                    <Loader2Icon className="animate-spin" />
                  ) : (
                    <RefreshCwIcon />
                  )}
                  Refresh
                </Button>
              </div>

              {form.github_data?.languages?.length ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  {form.github_data.languages.slice(0, 6).map((language) => (
                    <span
                      key={language}
                      className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground"
                    >
                      {language}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {form.github_synced_at
                    ? 'No languages found yet.'
                    : 'Press Refresh to pull your repos.'}
                </p>
              )}

              <p className="text-[11px] text-muted-foreground">
                Project details are stored for the agent and used in your messages — they are
                not shown here.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              Add your GitHub link above, then save. The agent will pull your public repos
              automatically.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
          Save changes
        </Button>
      </div>
    </main>
  )
}
