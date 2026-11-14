import type { ReactNode } from 'react'
import { CheckCircle2Icon, RadarIcon, SparklesIcon } from 'lucide-react'

import { Logo } from '@/components/logo'

const POINTS = [
  { icon: RadarIcon, text: 'Scans the home feed and keyword searches on X' },
  { icon: SparklesIcon, text: 'Writes a specific reply and DM for every real opening' },
  { icon: CheckCircle2Icon, text: 'Sends when confident, asks you when it is unsure' },
]

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden border-r border-border bg-muted/40 p-10 lg:flex">
        <div className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-20 size-80 rounded-full bg-sky-500/10 blur-3xl" />

        <div className="relative">
          <Logo href="/" />
        </div>

        <div className="relative max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            Fresh hiring posts.
            <br />
            Specific messages.
            <br />
            Your approval.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            JobPilot finds new roles on X, filters the noise, and writes outreach for the
            ones that actually fit your profile.
          </p>
          <ul className="mt-7 flex flex-col gap-3">
            {POINTS.map((point) => (
              <li key={point.text} className="flex items-start gap-2.5 text-sm">
                <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md bg-background text-muted-foreground ring-1 ring-border">
                  <point.icon className="size-3.5" />
                </span>
                <span className="text-muted-foreground">{point.text}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-[11px] text-muted-foreground">
          One flow · one account · everything logged
        </p>
      </section>

      <section className="flex items-center justify-center bg-gradient-to-b from-muted/30 via-background to-background px-4 py-12">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </main>
  )
}
