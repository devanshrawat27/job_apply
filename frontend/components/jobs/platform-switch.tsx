'use client'

import { cn } from '@/lib/utils'

export type Platform = 'all' | 'x' | 'linkedin'

const OPTIONS: { key: Platform; label: string }[] = [
  { key: 'all', label: 'All platforms' },
  { key: 'x', label: 'X' },
  { key: 'linkedin', label: 'LinkedIn' },
]

function PlatformMark({ platform, active }: { platform: Platform; active: boolean }) {
  if (platform === 'all') {
    return (
      <span
        className={cn(
          'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold',
          active ? 'bg-background/20 text-background' : 'bg-muted text-muted-foreground',
        )}
      >
        *
      </span>
    )
  }
  if (platform === 'linkedin') {
    return (
      <span
        className={cn(
          'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold leading-none',
          active ? 'bg-background text-sky-700' : 'bg-sky-600 text-white',
        )}
      >
        in
      </span>
    )
  }
  return (
    <span
      className={cn(
        'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold leading-none',
        active ? 'bg-background text-foreground' : 'bg-foreground text-background',
      )}
    >
      X
    </span>
  )
}

export function PlatformSwitch({
  value,
  onChange,
  counts,
}: {
  value: Platform
  onChange: (platform: Platform) => void
  counts: Record<Platform, number>
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-muted/20 p-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="px-1">
        <p className="text-xs font-medium">Platform</p>
        <p className="text-[11px] text-muted-foreground">
          Show jobs from one platform at a time.
        </p>
      </div>
      <div className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-background p-1">
        {OPTIONS.map((option) => {
          const active = value === option.key
          return (
            <button
              key={option.key}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(option.key)}
              className={cn(
                'flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors sm:px-3',
                active
                  ? 'bg-foreground text-background shadow-sm'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
              )}
            >
              <PlatformMark platform={option.key} active={active} />
              <span>{option.label}</span>
              <span
                className={cn(
                  'grid min-w-4 place-items-center rounded-full px-1 text-[10px] tabular-nums',
                  active ? 'bg-background/20 text-background' : 'bg-muted text-muted-foreground',
                )}
              >
                {counts[option.key] ?? 0}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
