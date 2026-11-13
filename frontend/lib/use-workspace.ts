'use client'

import { useCallback, useEffect, useState } from 'react'

import { api } from '@/lib/api'
import { onDataChanged } from '@/lib/events'
import type { Account, AgentSettings, Dashboard, Profile } from '@/lib/types'

export interface WorkspaceState {
  profile: Profile | null
  settings: AgentSettings | null
  account: Account | null
  dashboard: Dashboard | null
}

export function useWorkspace() {
  const [state, setState] = useState<WorkspaceState>({
    profile: null,
    settings: null,
    account: null,
    dashboard: null,
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [profile, settings, accounts, dashboard] = await Promise.all([
        api.getProfile(),
        api.getSettings(),
        api.accounts(),
        api.dashboard(),
      ])
      setState({ profile, settings, account: accounts[0] ?? null, dashboard })
      setError(null)
    } catch (err) {
      setError(
        `${(err as Error).message} — is the backend running on http://localhost:8000?`,
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
    const off = onDataChanged(() => void reload())
    const onFocus = () => void reload()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      off()
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [reload])

  return { ...state, loading, error, reload, setState }
}
