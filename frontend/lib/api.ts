import type {
  Account,
  AgentSettings,
  AuthStatus,
  Dashboard,
  Health,
  Insight,
  Job,
  KeywordsSnapshot,
  LLMKey,
  OutreachItem,
  Profile,
  ResumeDoc,
  Run,
  TokenPair,
  WatcherReport,
} from './types'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './auth-storage'
import { notifyDataChanged } from './events'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

let refreshPromise: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  const refresh = getRefreshToken()
  if (!refresh) return false

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
        cache: 'no-store',
      })
      if (!res.ok) return false
      const data = (await res.json()) as TokenPair
      setTokens(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshPromise = null
    }
  })()

  return refreshPromise
}

function authHeaders(headers?: HeadersInit): Record<string, string> {
  const token = getAccessToken()
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((headers as Record<string, string>) || {}),
  }
}

async function request<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...authHeaders(init?.headers),
    },
    cache: 'no-store',
  })

  if (
    res.status === 401 &&
    retry &&
    !path.startsWith('/auth/login') &&
    !path.startsWith('/auth/register')
  ) {
    if (await refreshTokens()) {
      return request<T>(path, init, false)
    }
    clearTokens()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      const detail = body?.detail
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map((d) => d.msg).join(', ')
    } catch {
      /* keep the status message */
    }
    throw new Error(message)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** Any write can change counters elsewhere; tell every mounted widget. */
async function mutate<T>(path: string, init?: RequestInit): Promise<T> {
  const result = await request<T>(path, init)
  notifyDataChanged()
  return result
}

export interface ResumedProfile {
  filename: string
  chars: number
  extracted: Record<string, unknown>
}

export const api = {
  health: () => request<Health>('/health'),

  authStatus: () => request<AuthStatus>('/auth/status'),
  login: (email: string, password: string) =>
    request<TokenPair>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  register: (email: string, password: string) =>
    request<TokenPair>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  logout: async () => {
    const refresh_token = getRefreshToken()
    try {
      await request('/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token }),
      })
    } catch {
      /* clearing local tokens is enough */
    }
    clearTokens()
  },
  me: () => request<{ id: number; email: string; is_active: boolean }>('/auth/me'),

  getProfile: () => request<Profile>('/profile'),
  saveProfile: (payload: Partial<Profile>) =>
    request<Profile>('/profile', { method: 'PUT', body: JSON.stringify(payload) }),
  uploadResume: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ResumedProfile>('/profile/resume', { method: 'POST', body: form })
  },

  resumes: () => request<ResumeDoc[]>('/profile/resumes'),
  addResume: (file: File, label: string, makePrimary: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('label', label)
    form.append('make_primary', String(makePrimary))
    return request<ResumeDoc>('/profile/resumes', { method: 'POST', body: form })
  },
  makePrimaryResume: (id: number) =>
    request<ResumeDoc>(`/profile/resumes/${id}/primary`, { method: 'POST' }),
  deleteResume: (id: number) =>
    request<{ deleted: boolean }>(`/profile/resumes/${id}`, { method: 'DELETE' }),

  accounts: () => request<Account[]>('/accounts'),
  connect: (payload: {
    username: string
    password: string
    verification_code?: string
    dm_passcode?: string
  }) => request<Account>('/accounts/connect', { method: 'POST', body: JSON.stringify(payload) }),
  disconnect: (id: number) => request<{ deleted: boolean }>(`/accounts/${id}`, { method: 'DELETE' }),
  setDmPasscode: (id: number, passcode: string | null) =>
    request<Account>(`/accounts/${id}/dm-passcode`, {
      method: 'PUT',
      body: JSON.stringify({ passcode }),
    }),

  getSettings: () => request<AgentSettings>('/settings'),
  syncGithub: () =>
    mutate<{ ok: boolean; username: string; summary: string }>('/profile/github/sync', {
      method: 'POST',
    }),
  saveSettings: (payload: Partial<AgentSettings>) =>
    request<AgentSettings>('/settings', { method: 'PUT', body: JSON.stringify(payload) }),

  jobs: (params: {
    status?: string
    q?: string
    has_link?: boolean
    open_only?: boolean
    sort?: string
  } = {}) => {
    const search = new URLSearchParams()
    if (params.status && params.status !== 'all') search.set('status', params.status)
    if (params.q) search.set('q', params.q)
    if (params.has_link) search.set('has_link', 'true')
    if (params.open_only) search.set('open_only', 'true')
    if (params.sort) search.set('sort', params.sort)
    const qs = search.toString()
    return request<Job[]>(`/jobs${qs ? `?${qs}` : ''}`)
  },
  jobStats: () =>
    request<{
      by_status: Record<string, number>
      total: number
      sent: number
      pending: number
      apply_links: number
    }>('/jobs/stats'),
  decide: (id: number, payload: { approved: boolean; reply_text?: string; dm_text?: string }) =>
    mutate<Job>(`/jobs/${id}/decide`, { method: 'POST', body: JSON.stringify(payload) }),
  sendNow: (id: number, payload: { reply_text?: string; dm_text?: string } = {}) =>
    mutate<Job>(`/jobs/${id}/send`, { method: 'POST', body: JSON.stringify(payload) }),
  reportFake: (id: number) => mutate<Job>(`/jobs/${id}/report-fake`, { method: 'POST' }),
  markApplied: (id: number) => mutate<Job>(`/jobs/${id}/mark-applied`, { method: 'POST' }),
  retryDm: (id: number) => mutate<Job>(`/jobs/${id}/retry-dm`, { method: 'POST' }),
  redraftJob: (id: number) => mutate<Job>(`/jobs/${id}/redraft`, { method: 'POST' }),
  aiFilter: (payload: { scope: 'pending' | 'apply_links' | 'all'; limit?: number; force?: boolean }) =>
    mutate<{ checked: number; rejected: number; matched: number; remaining: number }>(
      '/jobs/ai-filter',
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  scanNow: () => mutate<Run>('/runs/scan', { method: 'POST' }),
  sendQueued: () => mutate<Run>('/runs/send', { method: 'POST' }),
  runs: () => request<Run[]>('/runs'),
  keywords: () => request<KeywordsSnapshot>('/keywords'),
  pinKeyword: (keyword: string, pinned: boolean) =>
    mutate<{ keyword: string; pinned: boolean }>('/keywords/pin', {
      method: 'POST',
      body: JSON.stringify({ keyword, pinned }),
    }),
  llmKeys: () => request<LLMKey[]>('/llm/keys'),
  saveLLMKey: (payload: {
    label: string
    provider: string
    api_key: string
    base_url: string
    model: string
    enabled?: boolean
  }) => mutate<LLMKey>('/llm/keys', { method: 'POST', body: JSON.stringify(payload) }),
  deleteLLMKey: (id: number) => mutate<{ ok: boolean }>(`/llm/keys/${id}`, { method: 'DELETE' }),
  testLLMKey: (id: number) =>
    mutate<{ ok: boolean; model: string }>(`/llm/keys/${id}/test`, { method: 'POST' }),
  insightLatest: () => request<{ insight: Insight | null }>('/llm/insights/latest'),
  refreshInsight: () =>
    mutate<{ insight: Insight }>('/llm/insights/refresh', { method: 'POST' }),
  chatgptStatus: () =>
    request<{ connected: boolean; enabled: boolean; profile: string }>('/llm/chatgpt/status'),
  chatgptAccount: () =>
    request<{ email: string; name: string; plan: string }>('/llm/chatgpt/account'),
  watcherLatest: () =>
    request<{ report: WatcherReport | null }>('/llm/watcher/latest'),
  watcherCheck: () =>
    mutate<{ report: WatcherReport }>('/llm/watcher/check', { method: 'POST' }),
  connectChatgpt: () =>
    mutate<{ connected: boolean; enabled: boolean }>('/llm/chatgpt/connect', { method: 'POST' }),
  disconnectChatgpt: () =>
    mutate<{ connected: boolean; enabled: boolean }>('/llm/chatgpt/disconnect', {
      method: 'POST',
    }),
  outreach: (action?: string) =>
    request<OutreachItem[]>(`/outreach${action && action !== 'all' ? `?action=${action}` : ''}`),
  outreachSummary: () =>
    request<{ reply: number; dm: number; email: number; follow: number; apply: number }>(
      '/outreach/summary',
    ),
  dashboard: () => request<Dashboard>('/dashboard'),
}

export { BASE as API_BASE }
