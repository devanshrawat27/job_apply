export type JobStatus =
  | 'new'
  | 'rejected'
  | 'pending_approval'
  | 'queued'
  | 'retry_wait'
  | 'sending'
  | 'sent'
  | 'failed'
  | 'skipped'

export interface Profile {
  id: number
  full_name: string
  email: string
  phone: string
  location: string
  links: { github?: string; portfolio?: string; linkedin?: string }
  resume_text: string
  resume_filename: string
  job_title: string
  onboarding_completed: boolean
  domain: 'tech' | 'non-tech'
  skills: string[]
  target_roles: string[]
  extra_keywords: string[]
  locations: string[]
  avoid: string[]
  seniority: string
  experience_months: number
  current_company: string
  current_role: string
  min_salary: string
  remote_ok: boolean
  tone: string
  pitch: string
  github_username?: string
  github_summary?: string
  github_data?: {
    login?: string
    public_repos?: number
    stars?: number
    languages?: string[]
    projects?: { name: string; description: string; language: string; stars: number; url: string }[]
    active_days_ago?: number | null
  }
  github_synced_at?: string | null
  updated_at?: string | null
}

export interface Account {
  id: number
  username: string
  display_name: string
  status: string
  has_session: boolean
  has_dm_passcode: boolean
  last_checked_at: string | null
}

export interface AgentSettings {
  enabled: boolean
  scan_interval_minutes: number
  max_posts_per_scan: number
  lookback_hours: number
  relevance_threshold: number
  auto_send_confidence: number
  auto_send_enabled: boolean
  daily_reply_cap: number
  daily_dm_cap: number
  min_minutes_between_writes: number
  quiet_hours: string
  use_public_reply: boolean
  send_dms: boolean
  follow_when_needed: boolean
  reported_handles: string[]
  extra_queries: string[]
  chatgpt_browser_enabled: boolean
  closed_inbox_handles?: string[]
}

export interface Job {
  id: number
  post_id: string
  post_url: string
  author_handle: string
  author_name: string
  content: string
  posted_at: string | null
  discovered_at: string
  relevance: number
  company: string
  role: string
  job_location: string
  apply_method: string
  contact: string
  apply_url: string
  contact_email: string
  outreach_method: 'dm' | 'email' | 'link' | 'reply'
  decision_reason: string
  author_type: 'person' | 'company' | 'job_board'
  required_experience_months: number
  reason: string
  query_text: string
  resume_id: number
  resume_label: string
  spam_score: number
  spam_reasons: string[]
  followed: boolean
  generic_draft: boolean
  email_status: string
  confidence: number
  uncertainties: string[]
  reply_text: string
  dm_text: string
  status: JobStatus
  reply_status: string
  dm_status: string
  last_error: string
  decided_at: string | null
  sent_at: string | null
  ai_fit: number
  ai_note: string
  incoming_reply_at: string | null
  incoming_reply_text: string
  logs: string[]
}

export interface Run {
  id: number
  kind: string
  status: string
  started_at: string
  finished_at: string | null
  stats: Record<string, unknown>
  error: string
}

export interface Dashboard {  agent: { running: boolean; busy: boolean; last_scan: string | null }
  enabled: boolean
  usage: {
    replies_today: number
    dms_today: number
    daily_reply_cap: number
    daily_dm_cap: number
    quiet_hours: string
    in_quiet_hours: boolean
  }
  pending_approvals: number
  apply_links: number
  last_run: {
    id: number
    kind: string
    status: string
    stats: Record<string, unknown>
    finished_at: string | null
  } | null
}

export interface OutreachItem {
  id: number
  action: 'reply' | 'dm' | 'email' | 'follow' | 'apply'
  status: string
  target: string
  content: string
  detail: string
  created_at: string | null
  job_id: number
  post_url: string
  author_handle: string
  company: string
  role: string
  outreach_method: string
}

export interface ResumeDoc {
  id: number
  label: string
  filename: string
  is_primary: boolean
  chars: number
  created_at: string | null
}

export interface KeywordStat {
  keyword: string
  score: number
  uses: number
  posts_seen: number
  posts_relevant: number
  replies?: number
  pinned?: boolean
}

export interface KeywordsSnapshot {
  active: KeywordStat[]
  testing: KeywordStat[]
}

export interface Health {
  status: string
  llm_configured: boolean
  llm_model: string | null
  email_configured: boolean
  executor: {
    available: boolean
    node: string | null
    missing_scripts: string[]
    dependencies_installed: boolean
  }
}

export interface AuthStatus {
  auth_enabled: boolean
  has_user: boolean
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface LLMKey {
  id: number
  label: string
  provider: string
  masked: string
  base_url: string
  model: string
  enabled: boolean
}

export interface InsightPayload {
  keyword_verdicts: { keyword: string; verdict: string; why: string }[]
  new_keywords: { keyword: string; why: string }[]
  message_tips: string[]
  best_post_types: string[]
}

export interface Insight {
  id: number
  kind: string
  summary: string
  payload: InsightPayload
  created_at: string | null
}

export interface WatcherReport {
  id: number
  summary: string
  payload: {
    health: string
    summary: string
    problems: string[]
    next_actions: string[]
    note_for_user: string
    activity?: {
      since?: string
      totals?: Record<string, number>
      outreach?: string
      state?: string
    }
  }
  created_at: string | null
}
