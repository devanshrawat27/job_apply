import Link from 'next/link'
import {
  ArrowRightIcon,
  CheckIcon,
  MessageSquareIcon,
  ScanSearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from 'lucide-react'

import { Logo } from '@/components/logo'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const FEATURES = [
  {
    icon: ScanSearchIcon,
    title: 'Finds the posts',
    body: 'Scans the home feed and keyword searches every few minutes, then drops duplicates, job-seeker posts and fakes.',
  },
  {
    icon: MessageSquareIcon,
    title: 'Writes the outreach',
    body: 'A specific reply and DM for each post, built around the role and your real projects. Never a copy-paste template.',
  },
  {
    icon: ShieldCheckIcon,
    title: 'Knows when to stop',
    body: 'Experience gates, daily caps and closed-inbox checks. Anything uncertain waits for one click from you.',
  },
]

const STEPS = [
  {
    n: '01',
    title: 'Set up once',
    body: 'Upload a resume, add your GitHub, connect X. The agent learns your stack and target roles.',
  },
  {
    n: '02',
    title: 'It reads X for you',
    body: 'Fresh hiring posts are found, filtered and scored against your profile before a single message is written.',
  },
  {
    n: '03',
    title: 'You approve, it sends',
    body: 'Confident matches go out on their own. Everything else lands in Approvals with the exact reason.',
  },
]

export default function LandingPage() {
  return (
    <main className="min-h-screen overflow-x-hidden">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-3.5">
          <Logo href="/" />
          <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
            <a href="#features" className="transition-colors hover:text-foreground">
              Features
            </a>
            <a href="#how" className="transition-colors hover:text-foreground">
              How it works
            </a>
          </nav>
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
        </div>
      </header>

      {/* hero */}
      <section className="relative">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(60%_50%_at_70%_0%,rgba(56,189,248,0.14),transparent_70%)]" />
        <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-5 pb-20 pt-14 lg:grid-cols-[1.05fr_0.95fr] lg:pt-24">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-[11px] text-muted-foreground">
              <SparklesIcon className="size-3.5 text-amber-500" />
              For freshers and early-career developers
            </span>

            <h1 className="mt-6 text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl lg:text-6xl">
              Your job search,
              <br />
              <span className="bg-gradient-to-r from-sky-500 to-emerald-500 bg-clip-text text-transparent">
                on autopilot.
              </span>
            </h1>

            <p className="mt-5 max-w-lg text-sm leading-relaxed text-muted-foreground sm:text-base">
              JobPilot finds fresh hiring posts on X, writes a personal reply and DM for
              each real opening, and applies when it is confident. You keep the final say.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/signup" className={cn(buttonVariants({ size: 'lg' }), 'gap-2')}>
                Create free workspace
                <ArrowRightIcon className="size-4" />
              </Link>
              <Link
                href="/login"
                className={cn(buttonVariants({ variant: 'outline', size: 'lg' }))}
              >
                I already have an account
              </Link>
            </div>

            <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
              {['Own machine', 'Encrypted X session', 'Separate data per account'].map(
                (item) => (
                  <li key={item} className="inline-flex items-center gap-1.5">
                    <CheckIcon className="size-3 text-emerald-500" />
                    {item}
                  </li>
                ),
              )}
            </ul>
          </div>

          {/* product preview */}
          <div className="relative mx-auto w-full max-w-md">
            <div className="absolute -inset-4 -z-10 rounded-3xl bg-gradient-to-br from-sky-500/10 via-transparent to-emerald-500/10 blur-xl" />
            <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-xl shadow-black/5">
              <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                <span className="text-[11px] font-medium text-muted-foreground">
                  Approvals
                </span>
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
                  1 needs you
                </span>
              </div>

              <div className="flex items-start gap-2 border-b border-amber-500/20 bg-amber-500/[0.06] px-4 py-2.5">
                <SparklesIcon className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
                <p className="text-[11px] leading-relaxed text-amber-800 dark:text-amber-200">
                  <span className="font-medium">Why this needs you: </span>
                  role asks for 4+ years, your profile shows 3 months.
                </p>
              </div>

              <div className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">Aarav Mehta</p>
                    <p className="text-[11px] text-muted-foreground">
                      @aarav_builds · 2h · remote
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                      92
                    </p>
                    <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400">
                      strong match
                    </span>
                  </div>
                </div>

                <p className="mt-3 rounded-lg border border-border bg-muted/20 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                  Hiring a full stack developer for an early-stage product. React, Node
                  and Postgres. DM me your best work.
                </p>

                <div className="mt-3 rounded-lg border border-border px-3 py-2">
                  <p className="text-[9px] font-medium uppercase tracking-widest text-muted-foreground">
                    Public reply
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed">
                    Built a React + Node product with Postgres at 3 months in. Happy to
                    share the two projects closest to this stack.
                  </p>
                </div>

                <div className="mt-3 flex items-center gap-2">
                  <span className="inline-flex h-7 items-center rounded-md border border-border px-2.5 text-[11px] text-muted-foreground">
                    Reject
                  </span>
                  <span className="inline-flex h-7 items-center gap-1 rounded-md bg-foreground px-2.5 text-[11px] font-medium text-background">
                    <CheckIcon className="size-3" />
                    Approve &amp; send
                  </span>
                </div>
              </div>
            </div>

            <div className="absolute -bottom-4 -left-3 hidden items-center gap-1.5 rounded-full border border-border bg-background px-3 py-1.5 text-[10px] font-medium shadow-sm sm:flex">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Reply sent · DM sent
            </div>
          </div>
        </div>
      </section>

      {/* features */}
      <section id="features" className="border-t border-border">
        <div className="mx-auto w-full max-w-6xl px-5 py-16">
          <div className="max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              What it does
            </p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
              Three jobs. One pipeline.
            </h2>
          </div>

          <div className="mt-10 grid gap-8 sm:grid-cols-3">
            {FEATURES.map((feature) => (
              <div key={feature.title}>
                <span className="grid size-9 place-items-center rounded-lg border border-border bg-muted/40">
                  <feature.icon className="size-4" />
                </span>
                <h3 className="mt-3 text-sm font-semibold">{feature.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {feature.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* how it works */}
      <section id="how" className="border-t border-border bg-muted/20">
        <div className="mx-auto w-full max-w-6xl px-5 py-16">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                How it works
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
                Set it up once. It keeps working.
              </h2>
            </div>
            <Link
              href="/signup"
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'gap-1.5')}
            >
              Start free
              <ArrowRightIcon className="size-3.5" />
            </Link>
          </div>

          <div className="mt-10 grid gap-8 sm:grid-cols-3">
            {STEPS.map((step) => (
              <div key={step.n} className="border-t border-border pt-4">
                <span className="text-xs font-semibold tabular-nums text-sky-500">{step.n}</span>
                <h3 className="mt-1 text-sm font-semibold">{step.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {step.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* cta */}
      <section className="border-t border-border">
        <div className="mx-auto w-full max-w-6xl px-5 py-16">
          <div className="relative overflow-hidden rounded-2xl bg-foreground px-6 py-12 text-center text-background sm:px-12">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(50%_60%_at_50%_0%,rgba(255,255,255,0.16),transparent_70%)]" />
            <h2 className="relative text-2xl font-semibold tracking-tight sm:text-3xl">
              Stop refreshing X for openings.
            </h2>
            <p className="relative mx-auto mt-2 max-w-md text-sm text-background/70">
              Let the agent read the timeline while you prepare for interviews.
            </p>
            <Link
              href="/signup"
              className={cn(
                buttonVariants({ variant: 'secondary', size: 'lg' }),
                'relative mt-6 gap-2',
              )}
            >
              Create your workspace
              <ArrowRightIcon className="size-4" />
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-[11px] text-muted-foreground">
          <span>© {new Date().getFullYear()} JobPilot · one flow, one account per workspace</span>
          <div className="flex gap-4">
            <Link href="/login" className="transition-colors hover:text-foreground">
              Log in
            </Link>
            <Link href="/signup" className="transition-colors hover:text-foreground">
              Sign up
            </Link>
          </div>
        </div>
      </footer>
    </main>
  )
}
