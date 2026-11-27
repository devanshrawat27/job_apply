'use client'

import { LayoutGridIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

export type Platform = 'all' | 'x' | 'linkedin' | 'naukri'

const OPTIONS: { key: Platform; label: string; short: string }[] = [
  { key: 'all', label: 'All platforms', short: 'All' },
  { key: 'x', label: 'X', short: 'X' },
  { key: 'linkedin', label: 'LinkedIn', short: 'LinkedIn' },
  { key: 'naukri', label: 'Naukri', short: 'Naukri' },
]

function activeButton(platform: Platform): string {
  if (platform === 'linkedin') return 'bg-[#0a66c2] text-white shadow-sm'
  if (platform === 'naukri') return 'bg-[#ff7555] text-white shadow-sm'
  if (platform === 'x') return 'bg-foreground text-background shadow-sm'
  return 'bg-foreground/10 text-foreground shadow-sm ring-1 ring-foreground/15'
}

function activeCount(platform: Platform): string {
  if (platform === 'linkedin' || platform === 'naukri') return 'bg-white/20 text-white'
  if (platform === 'x') return 'bg-background/20 text-background'
  return 'bg-muted text-foreground'
}

function PlatformMark({ platform, active }: { platform: Platform; active: boolean }) {
  if (platform === 'all') {
    return (
      <LayoutGridIcon
        className={cn('size-3.5', active ? 'text-foreground' : 'text-muted-foreground')}
      />
    )
  }
  if (platform === 'linkedin') {
    return (
      <span
        className={cn(
          'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold leading-none',
          active ? 'bg-white text-[#0a66c2]' : 'bg-[#0a66c2] text-white',
        )}
      >
        in
      </span>
    )
  }
  if (platform === 'naukri') {
    return (
      <span
        className={cn(
          'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold leading-none',
          active ? 'bg-white text-[#ff7555]' : 'bg-[#ff7555] text-white',
        )}
      >
        N
      </span>
    )
  }
  return (
    <span
      className={cn(
        'grid size-4 place-items-center rounded-[4px] text-[9px] font-bold leading-none',
        active ? 'bg-background text-foreground' : 'bg-muted text-muted-foreground',
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
      <div className="grid grid-cols-4 gap-1 rounded-lg bg-muted/60 p-1">
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
                  ? activeButton(option.key)
                  : 'text-foreground/70 hover:bg-background/60 hover:text-foreground',
              )}
            >
              <PlatformMark platform={option.key} active={active} />
              <span>
                <span className="hidden sm:inline">{option.label}</span>
                <span className="sm:hidden">{option.short}</span>
              </span>
              <span
                className={cn(
                  'grid min-w-4 place-items-center rounded-full px-1 text-[10px] tabular-nums',
                  active
                    ? activeCount(option.key)
                    : 'bg-background text-foreground/60',
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
