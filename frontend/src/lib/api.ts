const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    return JSON.stringify(body.detail)
  } catch {
    return response.statusText
  }
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export interface UserRead {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

function authHeaders(accessToken: string): HeadersInit {
  return { Authorization: `Bearer ${accessToken}` }
}

export const authApi = {
  register(email: string, password: string) {
    return apiFetch<UserRead>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },

  login(email: string, password: string) {
    const form = new URLSearchParams({ username: email, password })
    return apiFetch<TokenPair>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    })
  },

  me(accessToken: string) {
    return apiFetch<UserRead>('/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
  },

  refresh(refreshToken: string) {
    return apiFetch<TokenPair>('/auth/refresh', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  },
}

// --- Profile Engine ---

export interface ProfileLink {
  id: string
  label: string
  url: string
}

export interface Profile {
  id: string
  headline: string | null
  summary: string | null
  location: string | null
  links: ProfileLink[]
  created_at: string
  updated_at: string
}

export interface ProfileUpdateInput {
  headline?: string | null
  summary?: string | null
  location?: string | null
}

export interface WorkExperience {
  id: string
  company: string
  title: string
  location: string | null
  start_date: string
  end_date: string | null
  description: string | null
}

export interface WorkExperienceInput {
  company: string
  title: string
  location?: string | null
  start_date: string
  end_date?: string | null
  description?: string | null
}

export interface Education {
  id: string
  institution: string
  degree: string | null
  field: string | null
  start_date: string | null
  end_date: string | null
}

export interface EducationInput {
  institution: string
  degree?: string | null
  field?: string | null
  start_date?: string | null
  end_date?: string | null
}

export type SkillLevel = 'beginner' | 'intermediate' | 'advanced' | 'expert'

export interface SkillVersion {
  id: string
  level: SkillLevel
  evidence: string
  evidence_url: string | null
  work_experience_id: string | null
  asserted_at: string
}

export interface Skill {
  id: string
  name: string
  category: string | null
  created_at: string
  versions: SkillVersion[]
}

export interface SkillVersionInput {
  level: SkillLevel
  evidence: string
  evidence_url?: string | null
  work_experience_id?: string | null
}

export type RemotePreference = 'remote' | 'hybrid' | 'onsite' | 'no_preference'

export interface Preferences {
  job_types: string[]
  remote_preference: RemotePreference
  locations: string[]
  salary_min: number | null
  salary_max: number | null
  industries_include: string[]
  industries_exclude: string[]
  deal_breakers: string | null
  updated_at: string
}

export interface PreferencesInput {
  job_types?: string[]
  remote_preference?: RemotePreference
  locations?: string[]
  salary_min?: number | null
  salary_max?: number | null
  industries_include?: string[]
  industries_exclude?: string[]
  deal_breakers?: string | null
}

// --- Research Engine ---

export type ResearchQueryStatus = 'pending' | 'running' | 'completed' | 'failed'
export type SourceTier = 'official' | 'government' | 'docs' | 'reputable_secondary' | 'forum_anecdotal' | 'unknown'
export type ClaimStatus = 'corroborated' | 'single_source' | 'contradicted' | 'unverified'
export type CitationStance = 'supports' | 'contradicts' | 'context_only'

export interface ResearchQuery {
  id: string
  query_text: string
  purpose: string | null
  status: ResearchQueryStatus
  error: string | null
  created_at: string
  completed_at: string | null
}

export interface ResearchSource {
  id: string
  original_url: string
  domain: string
  title: string | null
  tier: SourceTier
  tier_rationale: string
  http_status: number | null
  fetch_error: string | null
  fetched_at: string | null
  published_at: string | null
}

export interface ResearchCitation {
  id: string
  source_id: string
  excerpt: string
  stance: CitationStance
  excerpt_verified: boolean
}

export interface ResearchClaim {
  id: string
  claim_text: string
  claim_type: string | null
  value: Record<string, unknown> | null
  status: ClaimStatus
  confidence_score: number
  confidence_rationale: string
  citations: ResearchCitation[]
}

export interface ResearchReport {
  id: string
  summary: string
  uncertainties: string[]
  claim_ids: string[]
  model_used: string | null
  generated_at: string
}

export interface ResearchQueryDetail extends ResearchQuery {
  sources: ResearchSource[]
  claims: ResearchClaim[]
  report: ResearchReport | null
}

export interface ResearchQueryInput {
  query_text: string
  purpose?: string | null
}

export const researchApi = {
  list(token: string) {
    return apiFetch<ResearchQuery[]>('/research/queries', { headers: authHeaders(token) })
  },
  create(token: string, input: ResearchQueryInput) {
    return apiFetch<ResearchQuery>('/research/queries', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  get(token: string, id: string) {
    return apiFetch<ResearchQueryDetail>(`/research/queries/${id}`, { headers: authHeaders(token) })
  },
}

// --- Semantic search ---

export type SearchResultType =
  | 'bio'
  | 'work_experience'
  | 'education'
  | 'skill_evidence'
  | 'preferences'
  | 'research_claim'
  | 'research_source'

export type SearchLinkKind = 'profile' | 'research'

export interface SearchResultLink {
  kind: SearchLinkKind
  query_id: string | null
  anchor: string | null
}

export interface SearchResult {
  id: string
  type: SearchResultType
  title: string
  snippet: string
  link: SearchResultLink
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
}

export const searchApi = {
  search(token: string, q: string) {
    return apiFetch<SearchResponse>(`/search?q=${encodeURIComponent(q)}`, {
      headers: authHeaders(token),
    })
  },
}

// --- Gmail (read-only) ---

export type GmailConnectionStatus = 'connected' | 'needs_reauth' | 'disconnected'
export type GmailSyncRunStatus = 'pending' | 'running' | 'completed' | 'failed'
export type GmailSyncType = 'backfill' | 'incremental'

export interface GmailConnection {
  id: string
  google_email: string
  status: GmailConnectionStatus
  last_synced_at: string | null
  last_sync_error: string | null
  created_at: string
}

export interface GmailSyncRun {
  id: string
  sync_type: GmailSyncType
  status: GmailSyncRunStatus
  messages_fetched: number
  messages_stored: number
  error: string | null
  started_at: string
  completed_at: string | null
}

export interface EmailMessageSummary {
  id: string
  gmail_message_id: string
  thread_id: string
  subject: string | null
  from_address: string | null
  to_addresses: string[]
  date: string | null
  snippet: string
  label_ids: string[]
}

export const gmailApi = {
  getConnection(token: string) {
    return apiFetch<GmailConnection>('/gmail/connection', { headers: authHeaders(token) })
  },
  oauthStart(token: string) {
    return apiFetch<{ authorization_url: string }>('/gmail/oauth/start', {
      headers: authHeaders(token),
    })
  },
  startSync(token: string) {
    return apiFetch<GmailSyncRun>('/gmail/sync', { method: 'POST', headers: authHeaders(token) })
  },
  listSyncRuns(token: string) {
    return apiFetch<GmailSyncRun[]>('/gmail/sync', { headers: authHeaders(token) })
  },
  listMessages(token: string, limit = 50) {
    return apiFetch<EmailMessageSummary[]>(`/gmail/messages?limit=${limit}`, {
      headers: authHeaders(token),
    })
  },
  disconnect(token: string, purgeData: boolean) {
    return apiFetch<GmailConnection>('/gmail/connection', {
      method: 'DELETE',
      headers: authHeaders(token),
      body: JSON.stringify({ purge_data: purgeData }),
    })
  },
}

export const profileApi = {
  get(token: string) {
    return apiFetch<Profile>('/profile', { headers: authHeaders(token) })
  },
  update(token: string, input: ProfileUpdateInput) {
    return apiFetch<Profile>('/profile', {
      method: 'PUT',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  addLink(token: string, input: { label: string; url: string }) {
    return apiFetch<ProfileLink>('/profile/links', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  deleteLink(token: string, id: string) {
    return apiFetch<void>(`/profile/links/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  },

  listExperience(token: string) {
    return apiFetch<WorkExperience[]>('/profile/experience', { headers: authHeaders(token) })
  },
  createExperience(token: string, input: WorkExperienceInput) {
    return apiFetch<WorkExperience>('/profile/experience', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  updateExperience(token: string, id: string, input: Partial<WorkExperienceInput>) {
    return apiFetch<WorkExperience>(`/profile/experience/${id}`, {
      method: 'PUT',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  deleteExperience(token: string, id: string) {
    return apiFetch<void>(`/profile/experience/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  },

  listEducation(token: string) {
    return apiFetch<Education[]>('/profile/education', { headers: authHeaders(token) })
  },
  createEducation(token: string, input: EducationInput) {
    return apiFetch<Education>('/profile/education', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  updateEducation(token: string, id: string, input: Partial<EducationInput>) {
    return apiFetch<Education>(`/profile/education/${id}`, {
      method: 'PUT',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  deleteEducation(token: string, id: string) {
    return apiFetch<void>(`/profile/education/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  },

  listSkills(token: string) {
    return apiFetch<Skill[]>('/profile/skills', { headers: authHeaders(token) })
  },
  createSkill(token: string, input: { name: string; category?: string | null }) {
    return apiFetch<Skill>('/profile/skills', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  deleteSkill(token: string, id: string) {
    return apiFetch<void>(`/profile/skills/${id}`, { method: 'DELETE', headers: authHeaders(token) })
  },
  addSkillVersion(token: string, skillId: string, input: SkillVersionInput) {
    return apiFetch<SkillVersion>(`/profile/skills/${skillId}/versions`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },

  getPreferences(token: string) {
    return apiFetch<Preferences>('/profile/preferences', { headers: authHeaders(token) })
  },
  updatePreferences(token: string, input: PreferencesInput) {
    return apiFetch<Preferences>('/profile/preferences', {
      method: 'PUT',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
}
