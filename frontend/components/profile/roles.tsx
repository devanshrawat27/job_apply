import { CheckIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

/** Roles a candidate usually wants to search for. */
export const JOB_TITLES = [
  'Frontend Developer',
  'Backend Developer',
  'Full Stack Developer',
  'React Developer',
  'Node.js Developer',
  'Python Developer',
  'Mobile Developer',
  'DevOps Engineer',
  'Data Scientist',
  'ML Engineer',
  'QA Engineer',
  'Software Engineer',
]

/**
 * Categories a candidate can mark as "not a fit". The value is the keyword the
 * backend matches against a post, so keep it short and literal.
 */
export const NOT_FIT_ROLES: { label: string; value: string }[] = [
  { label: 'Sales', value: 'sales' },
  { label: 'Marketing', value: 'marketing' },
  { label: 'UI / UX Design', value: 'designer' },
  { label: 'Product Management', value: 'product manager' },
  { label: 'Customer Support', value: 'customer support' },
  { label: 'HR / Recruiting', value: 'recruiter' },
  { label: 'QA / Testing', value: 'qa' },
  { label: 'DevOps / SRE', value: 'devops' },
  { label: 'Data / ML', value: 'data scientist' },
  { label: 'Mobile', value: 'mobile developer' },
]

export function selectedRoles(profile: {
  job_title: string
  target_roles: string[]
}): string[] {
  if (profile.target_roles?.length) return profile.target_roles
  return profile.job_title ? [profile.job_title] : []
}

export function toRolePatch(roles: string[]): { target_roles: string[]; job_title: string } {
  return { target_roles: roles, job_title: roles[0] || '' }
}

export function RoleChip({
  label,
  active,
  onClick,
  badge,
}: {
  label: string
  active: boolean
  onClick: () => void
  badge?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
        active
          ? 'border-foreground/30 bg-foreground/5 font-medium text-foreground'
          : 'border-border text-muted-foreground hover:bg-muted/40 hover:text-foreground',
      )}
    >
      {active ? <CheckIcon className="size-3" /> : null}
      {label}
      {active && badge ? (
        <span className="rounded-full bg-foreground/10 px-1.5 text-[10px] text-muted-foreground">
          {badge}
        </span>
      ) : null}
    </button>
  )
}
