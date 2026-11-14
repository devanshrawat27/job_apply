'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  ClipboardCheckIcon,
  ExternalLinkIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  RefreshCwIcon,
  ScrollTextIcon,
  SearchIcon,
  SendIcon,
  SettingsIcon,
  UserRoundIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { onDataChanged } from '@/lib/events'
import { cn } from '@/lib/utils'

type NavItem = {
  href: string
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Workspace',
    items: [
      {
        href: '/dashboard',
        label: 'Dashboard',
        description: 'Overview and alerts',
        icon: LayoutDashboardIcon,
      },
      {
        href: '/posts',
        label: 'Found posts',
        description: 'Every post the agent read',
        icon: SearchIcon,
      },
      {
        href: '/apply-links',
        label: 'Apply links',
        description: 'Posts with a direct apply link',
        icon: ExternalLinkIcon,
      },
      {
        href: '/approvals',
        label: 'Approvals',
        description: 'Drafts that need you',
        icon: ClipboardCheckIcon,
      },
      {
        href: '/outreach',
        label: 'Outreach',
        description: 'Replies, DMs, emails, follows',
        icon: SendIcon,
      },
    ],
  },
  {
    label: 'Account',
    items: [
      {
        href: '/profile',
        label: 'Profile',
        description: 'Resume and job preferences',
        icon: UserRoundIcon,
      },
      {
        href: '/activity',
        label: 'Activity',
        description: 'Runs and outcomes',
        icon: ScrollTextIcon,
      },
      {
        href: '/settings',
        label: 'Settings',
        description: 'Agent behaviour and limits',
        icon: SettingsIcon,
      },
    ],
  },
]

const MOBILE_ITEMS = NAV_GROUPS.flatMap((group) => group.items)

function useNavCounts(): { pending: number; links: number } {
  const [counts, setCounts] = useState({ pending: 0, links: 0 })

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const dash = await api.dashboard()
        if (active) {
          setCounts({ pending: dash.pending_approvals, links: dash.apply_links ?? 0 })
        }
      } catch {
        if (active) setCounts({ pending: 0, links: 0 })
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    const off = onDataChanged(() => void load())
    const onFocus = () => void load()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      active = false
      window.clearInterval(timer)
      off()
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [])

  return counts
}

function badgeFor(href: string, pending: number, links: number) {
  if (href === '/approvals' && pending > 0) {
    return { count: pending, tone: 'bg-amber-500' }
  }
  if (href === '/apply-links' && links > 0) {
    return { count: links, tone: 'bg-sky-500' }
  }
  return null
}

export function AppSidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const { pending, links } = useNavCounts()
  const [scanning, setScanning] = useState(false)

  async function signOut() {
    await api.logout()
    router.replace('/login')
  }

  async function scanNow() {
    setScanning(true)
    try {
      await api.scanNow()
      toast.success('Scan started')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setScanning(false)
    }
  }

  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-border bg-sidebar md:flex">
      <div className="flex h-16 items-center border-b border-border px-4">
        <Logo href="/dashboard" />
      </div>

      <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-1">
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              {group.label}
            </p>
            {group.items.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
              const badge = badgeFor(item.href, pending, links)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'group relative flex items-start gap-3 rounded-lg px-3 py-2 transition-colors',
                    active
                      ? 'bg-muted text-foreground'
                      : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                  )}
                >
                  {active ? (
                    <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-foreground" />
                  ) : null}
                  <item.icon
                    className={cn(
                      'mt-0.5 size-4 shrink-0',
                      active ? 'text-foreground' : 'text-muted-foreground',
                    )}
                  />
                  <span className="flex min-w-0 flex-col">
                    <span className="text-sm font-medium leading-5">{item.label}</span>
                    <span className="truncate text-[11px] leading-tight text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                  {badge ? (
                    <span
                      className={cn(
                        'ml-auto mt-0.5 grid min-w-5 place-items-center rounded-full px-1.5 text-[10px] font-semibold text-black',
                        badge.tone,
                      )}
                    >
                      {badge.count}
                    </span>
                  ) : null}
                </Link>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="flex flex-col gap-3 border-t border-border p-3">
        <Button
          size="sm"
          variant="outline"
          className="w-full justify-start"
          disabled={scanning}
          onClick={() => void scanNow()}
        >
          <RefreshCwIcon className={cn('size-4', scanning && 'animate-spin')} />
          {scanning ? 'Scanning…' : 'Scan now'}
        </Button>
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">Your workspace</p>
            <p className="truncate text-[11px] text-muted-foreground">1 flow · 1 X account</p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => void signOut()}
              title="Sign out"
              className="grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <LogOutIcon className="size-4" />
            </button>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </aside>
  )
}

export function MobileNav() {
  const pathname = usePathname()
  const { pending, links } = useNavCounts()

  return (
    <div className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur md:hidden">
      <div className="flex h-14 items-center justify-between px-4">
        <Logo href="/dashboard" />
        <ThemeToggle />
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-2">
        {MOBILE_ITEMS.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
          const badge = badgeFor(item.href, pending, links)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition-colors',
                active
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-muted/50',
              )}
            >
              <item.icon className="size-3.5" />
              {item.label}
              {badge ? (
                <span
                  className={cn(
                    'grid min-w-4 place-items-center rounded-full px-1 text-[9px] font-semibold text-black',
                    badge.tone,
                  )}
                >
                  {badge.count}
                </span>
              ) : null}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}
