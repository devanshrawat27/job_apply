'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'

import { Skeleton } from '@/components/ui/misc'
import { api } from '@/lib/api'
import { getAccessToken } from '@/lib/auth-storage'

export function WorkspaceGuard({ children }: { children: ReactNode }) {
  const router = useRouter()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const status = await api.authStatus()
        if (!active) return
        if (status.auth_enabled && !getAccessToken()) {
          router.replace('/login')
          return
        }

        const [profile, accounts] = await Promise.all([api.getProfile(), api.accounts()])
        if (!active) return
        if (!profile.onboarding_completed || accounts.length === 0) {
          router.replace('/onboarding')
          return
        }
      } catch {
        /* the page itself will surface the backend error */
      } finally {
        if (active) setChecked(true)
      }
    })()
    return () => {
      active = false
    }
  }, [router])

  if (!checked) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-10">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return <>{children}</>
}
