'use client'

import { useState, type ReactNode } from 'react'
import { CheckIcon, XIcon } from 'lucide-react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/misc'
import { cn } from '@/lib/utils'

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Label className="text-sm text-muted-foreground">{label}</Label>
      {children}
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export function ChipInput({
  label,
  hint,
  values,
  onChange,
  suggestions = [],
  placeholder = 'Add and press Enter',
  max = 30,
}: {
  label: string
  hint?: ReactNode
  values: string[]
  onChange: (next: string[]) => void
  suggestions?: string[]
  placeholder?: string
  max?: number
}) {
  const [draft, setDraft] = useState('')

  function add(value: string) {
    const clean = value.trim().replace(/,$/, '')
    if (!clean) return
    const exists = values.some((v) => v.toLowerCase() === clean.toLowerCase())
    if (!exists && values.length < max) onChange([...values, clean])
    setDraft('')
  }

  function remove(value: string) {
    onChange(values.filter((v) => v !== value))
  }

  return (
    <div className="flex flex-col gap-2">
      <Label className="text-sm text-muted-foreground">{label}</Label>

      {values.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-xs text-secondary-foreground"
            >
              {value}
              <button
                type="button"
                aria-label={`Remove ${value}`}
                className="text-muted-foreground hover:text-foreground"
                onClick={() => remove(value)}
              >
                <XIcon className="size-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}

      <Input
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            add(draft)
          }
          if (e.key === 'Backspace' && !draft && values.length) {
            onChange(values.slice(0, -1))
          }
        }}
        onBlur={() => add(draft)}
      />

      {suggestions.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {suggestions
            .filter((s) => !values.some((v) => v.toLowerCase() === s.toLowerCase()))
            .slice(0, 10)
            .map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => add(s)}
                className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                + {s}
              </button>
            ))}
        </div>
      ) : null}

      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

export function ChoiceChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
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
    </button>
  )
}
