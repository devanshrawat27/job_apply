import Link from 'next/link'
import {
  ArrowRightIcon,
  BotIcon,
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
    title: 'Scans X every 30 minutes',
    body: 'Curated hiring signals, fresher-friendly filters and your own keywords. No manual searching.',
  },
  {
    icon: BotIcon,
    title: 'Writes a personal reply + DM',
    body: 'Each message quotes the post and your stack, never a generic template. Multiple resumes, best one wins.',
  },
  {
    icon: ShieldCheckIcon,
    title: 'Sends only when sure',
    body: 'Fake-post detection, experience gates and daily caps. Low-confidence drafts wait for your approval.',
  },
  {
    icon: MessageSquareIcon,
    title: 'One clean timeline',
    body: 'Replies, DMs, emails and direct apply links in a single workspace, with the reason for every decision.',
  },
]

const STEPS = [
  { n: '01', title: 'Create your workspace', body: 'Sign up, upload a resume and connect your X account.' },
  { n: '02', title: 'The agent starts hunting', body: 'It scans fresh posts, ranks them against your resume and drafts outreach.' },
  { n: '03', title: 'Watch it apply', body: 'Strong matches go out automatically; unsure ones land in Approvals for one click.' },
]

export default function LandingPage() {
  return (
    <main className="min-h-screen">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-5">
        <Logo href="/" />
        <div className="flex items-center gap-2">
          <Link href="/login" className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}>
            Log in
          </Link>
          <Link href="/signup" className={cn(buttonVariants({ size: 'sm' }))}>
            Get started
            <ArrowRightIcon className="size-4" />
          </Link>
        </div>
      </header>

      <section className="mx-auto w-full max-w-6xl px-5 pt-10 pb-16 sm:pt-16">
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-3 py-1 text-[11px] text-muted-foreground">
            <SparklesIcon className="size-3.5 text-amber-500" />
            Built for fresher and early-career developers
          </span>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight sm:text-6xl">
            Your job search,
            <br className="hidden sm:block" /> on autopilot.
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            JobPilot finds fresh hiring posts on X, writes a personal reply and DM for each one,
            and applies when it is confident. You keep the final say.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
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
          <p className="mt-3 text-[11px] text-muted-foreground">
            Runs on your own machine · your X session is encrypted · data stays separate per account
          </p>
        </div>

        <div className="mt-14 grid gap-3 sm:grid-cols-2">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="rounded-2xl border border-border bg-card p-5">
              <feature.icon className="size-5 text-sky-500" />
              <h2 className="mt-3 text-sm font-semibold">{feature.title}</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{feature.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-14 rounded-2xl border border-border bg-muted/10 p-6">
          <h2 className="text-center text-sm font-semibold">How it works</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {STEPS.map((step) => (
              <div key={step.n}>
                <span className="text-xs font-semibold text-sky-500">{step.n}</span>
                <h3 className="mt-1 text-sm font-medium">{step.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.body}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-14 text-center">
          <h2 className="text-xl font-semibold tracking-tight">Stop refreshing X for openings.</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Let the agent read the timeline while you prepare for interviews.
          </p>
          <Link
            href="/signup"
            className={cn(buttonVariants({ size: 'lg' }), 'mt-5 gap-2')}
          >
            Get started
            <ArrowRightIcon className="size-4" />
          </Link>
        </div>
      </section>

      <footer className="border-t border-border px-5 py-6">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 text-[11px] text-muted-foreground">
          <span>© {new Date().getFullYear()} JobPilot — one flow, one account per workspace</span>
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
