import Link from 'next/link'
import {
  ArrowRightIcon,
  MessageSquareIcon,
  ScanSearchIcon,
  ShieldCheckIcon,
} from 'lucide-react'

import { Logo } from '@/components/logo'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const FEATURES = [
  {
    icon: ScanSearchIcon,
    title: 'Finds',
    body: 'Home feed and fresh keyword searches. Duplicates, job-seeker posts and fakes are removed.',
  },
  {
    icon: MessageSquareIcon,
    title: 'Writes',
    body: 'A reply and a DM for each post, built from the role, your stack and your GitHub projects.',
  },
  {
    icon: ShieldCheckIcon,
    title: 'Guards',
    body: 'Caps, cool-down and closed-inbox checks. Anything unsure waits for one click from you.',
  },
]

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-x-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[480px] bg-[radial-gradient(55%_60%_at_50%_0%,rgba(16,185,129,0.10),transparent_70%)]" />

      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-5 py-5">
        <Logo href="/" />
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
          >
            Log in
          </Link>
          <Link href="/signup" className={cn(buttonVariants({ size: 'sm' }), 'gap-1.5')}>
            Get started
            <ArrowRightIcon className="size-3.5" />
          </Link>
        </div>
      </header>

      <section className="mx-auto w-full max-w-3xl px-5 pb-16 pt-10 text-center sm:pt-20">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background/70 px-3 py-1 text-[11px] text-muted-foreground">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          For freshers and early-career developers
        </span>

        <h1 className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
          Job hunting on X,
          <br />
          handled.
        </h1>

        <p className="mx-auto mt-5 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
          JobPilot scans your feed and fresh hiring posts, writes a specific reply and DM
          for each real opening, and applies when it is confident. You approve the rest.
        </p>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Link href="/signup" className={cn(buttonVariants({ size: 'lg' }), 'gap-2')}>
            Create a workspace
            <ArrowRightIcon className="size-4" />
          </Link>
          <Link
            href="/login"
            className={cn(buttonVariants({ variant: 'outline', size: 'lg' }))}
          >
            I already have an account
          </Link>
        </div>

        <p className="mt-4 text-[11px] text-muted-foreground">
          No browser extension · encrypted X session · separate data per account
        </p>
      </section>

      {/* three points */}
      <section className="border-y border-border bg-muted/20">
        <div className="mx-auto grid w-full max-w-5xl gap-8 px-5 py-12 sm:grid-cols-3">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="flex items-start gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-border bg-background">
                <feature.icon className="size-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">{feature.title}</h2>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {feature.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto w-full max-w-5xl px-5 py-16">
        <div className="flex flex-col items-start justify-between gap-5 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              Stop refreshing X for openings.
            </h2>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Let the agent read the timeline while you prepare for interviews.
            </p>
          </div>
          <Link href="/signup" className={cn(buttonVariants({ size: 'lg' }), 'gap-2')}>
            Create a workspace
            <ArrowRightIcon className="size-4" />
          </Link>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-[11px] text-muted-foreground">
          <span>© {new Date().getFullYear()} JobPilot</span>
          <div className="flex gap-4">
            <Link href="/login" className="hover:text-foreground">
              Log in
            </Link>
            <Link href="/signup" className="hover:text-foreground">
              Sign up
            </Link>
          </div>
        </div>
      </footer>
    </main>
  )
}
