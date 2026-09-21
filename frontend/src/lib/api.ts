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

/** Lets the auth store plug token refresh into every request without api.ts importing it
 * (the store imports api.ts, so the reverse would be a cycle). */
export interface AuthHooks {
  getRefreshToken: () => string | null
  onRefreshed: (tokens: TokenPair) => void
  /** Refreshing failed too: the session is over and the user must sign in again. */
  onExpired: () => void
}

let authHooks: AuthHooks | null = null

export function configureAuthHooks(hooks: AuthHooks): void {
  authHooks = hooks
}

// One refresh at a time: a page fires several requests at once, and when the access token has
// expired they all get a 401 together — they must share a single refresh, not race.
let refreshInFlight: Promise<TokenPair | null> | null = null

function refreshAccessToken(): Promise<TokenPair | null> {
  if (refreshInFlight) return refreshInFlight
  const refreshToken = authHooks?.getRefreshToken()
  if (!authHooks || !refreshToken) return Promise.resolve(null)
  const hooks = authHooks

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!response.ok) return null
      const tokens = (await response.json()) as TokenPair
      hooks.onRefreshed(tokens)
      return tokens
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

function send(path: string, init: RequestInit): Promise<Response> {
  // Normalized through Headers (not object-spread) so callers may pass a plain object or a
  // Headers instance, and a caller-set Content-Type wins over the JSON default.
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  return fetch(`${API_URL}${path}`, { ...init, headers })
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response = await send(path, init)

  // An authenticated request that got a 401 usually just means the 30-minute access token
  // expired. Refresh once and retry; only if that fails is the session actually over.
  const hadToken = new Headers(init.headers).has('Authorization')
  if (response.status === 401 && hadToken && authHooks) {
    const tokens = await refreshAccessToken()
    if (tokens) {
      const headers = new Headers(init.headers)
      headers.set('Authorization', `Bearer ${tokens.access_token}`)
      response = await send(path, { ...init, headers })
    }
    if (response.status === 401) authHooks.onExpired()
  }

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

// --- GitHub (read-only) and the integrations overview ---

export type GithubConnectionStatus = 'connected' | 'needs_reauth' | 'disconnected'

export interface GithubInstallation {
  id: number | null
  account: string | null
  repository_selection: string | null
  permissions: Record<string, string>
}

export interface GithubConnection {
  id: string
  github_login: string
  status: GithubConnectionStatus
  installations: GithubInstallation[]
  last_error: string | null
  created_at: string
}

export interface GithubDisconnectResult {
  connection: GithubConnection
  revoked_at_github: boolean
}

export const githubApi = {
  getConnection(token: string) {
    return apiFetch<GithubConnection>('/github/connection', { headers: authHeaders(token) })
  },
  oauthStart(token: string) {
    return apiFetch<{ authorization_url: string }>('/github/oauth/start', {
      headers: authHeaders(token),
    })
  },
  disconnect(token: string) {
    return apiFetch<GithubDisconnectResult>('/github/connection', {
      method: 'DELETE',
      headers: authHeaders(token),
    })
  },
}

export type IntegrationStatus =
  | 'connected'
  | 'needs_reauth'
  | 'disconnected'
  | 'not_connected'
  | 'unavailable'

export interface Integration {
  key: string
  label: string
  status: IntegrationStatus
  summary: string
  path: string | null
  reason: string | null
}

export const integrationsApi = {
  list(token: string) {
    return apiFetch<Integration[]>('/integrations', { headers: authHeaders(token) })
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

// --- Career: jobs, verification, fraud, match ---

export type RemoteType = 'remote' | 'hybrid' | 'onsite' | 'unknown'
export type JobBoard = 'greenhouse' | 'lever' | 'ashby' | 'usajobs'
export type EmployerVerificationStatus = 'verified' | 'unconfirmed' | 'suspicious'
export type FraudRiskLevel = 'low' | 'medium' | 'high'
export type MatchStatus = 'running' | 'completed' | 'failed'
export type ComponentStatus = 'assessed' | 'not_assessed'
export type DealBreakerCheck = 'none_set' | 'checked' | 'unavailable'

export interface EmployerVerification {
  id: string
  employer_key: string
  verification_status: EmployerVerificationStatus
  confidence_score: number
  rationale: string
  checked_at: string
}

export interface FraudSignal {
  code: string
  description: string
}

export interface FraudAssessment {
  id: string
  risk_level: FraudRiskLevel
  risk_score: number
  signals: FraudSignal[]
  assessed_at: string
}

/** One line of a component's evidence. Which keys are present depends on the component
 * (skills carry requirement/quote/match_type/evidence; salary carries the two numbers, ...),
 * so it's deliberately loose — the UI renders the ones it knows and ignores the rest. */
export type MatchDetail = Record<string, unknown>

export interface MatchComponent {
  key: string
  label: string
  weight: number
  status: ComponentStatus
  fraction: number | null
  points: number | null
  summary: string
  reason: string | null
  details: MatchDetail[]
}

export interface DealBreakerHit {
  deal_breaker: string
  quote: string
}

export interface JobMatch {
  id: string
  status: MatchStatus
  error: string | null
  /** null (never 0) when nothing could be assessed. */
  score_percent: number | null
  /** Of the 100 points, how many were actually measurable. */
  assessed_weight: number
  low_confidence: boolean
  components: MatchComponent[]
  uncertainties: string[]
  deal_breaker_check: DealBreakerCheck
  deal_breaker_hits: DealBreakerHit[]
  /** The profile changed after this was computed. */
  is_stale: boolean
  computed_at: string
}

export interface CareerJob {
  id: string
  source_channel: string
  external_id: string | null
  source_url: string | null
  company_name: string | null
  company_domain: string | null
  title: string | null
  location: string | null
  remote_type: RemoteType
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  description_text: string | null
  posted_at: string | null
  discovered_at: string
  employer_verification: EmployerVerification | null
  fraud_assessment: FraudAssessment | null
  match: JobMatch | null
}

export interface JobBoardFeed {
  id: string
  board: JobBoard
  company_slug: string | null
  keyword: string | null
  is_active: boolean
  last_polled_at: string | null
  last_poll_error: string | null
}

export interface JobBoardFeedInput {
  board: JobBoard
  company_slug?: string | null
  keyword?: string | null
}

export const careerApi = {
  listJobs(token: string) {
    return apiFetch<CareerJob[]>('/career/jobs', { headers: authHeaders(token) })
  },
  createFromUrl(token: string, url: string) {
    return apiFetch<CareerJob>('/career/jobs/from-url', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ url }),
    })
  },
  createFromPaste(token: string, rawText: string) {
    return apiFetch<CareerJob>('/career/jobs/paste', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ raw_text: rawText }),
    })
  },
  matchJob(token: string, id: string) {
    return apiFetch<{ status: string }>(`/career/jobs/${id}/match`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
  verifyJob(token: string, id: string) {
    return apiFetch<{ status: string }>(`/career/jobs/${id}/verify`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
  listFeeds(token: string) {
    return apiFetch<JobBoardFeed[]>('/career/jobs/feeds', { headers: authHeaders(token) })
  },
  createFeed(token: string, input: JobBoardFeedInput) {
    return apiFetch<JobBoardFeed>('/career/jobs/feeds', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  deleteFeed(token: string, id: string) {
    return apiFetch<void>(`/career/jobs/feeds/${id}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    })
  },
  pollFeed(token: string, id: string) {
    return apiFetch<{ status: string }>(`/career/jobs/feeds/${id}/poll`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
}

// --- Career: application tracker ---

export type ApplicationStatus =
  | 'saved'
  | 'applied'
  | 'screening'
  | 'interviewing'
  | 'offer'
  | 'accepted'
  | 'rejected'
  | 'withdrawn'
  | 'no_response'
export type ApplicationEventType = 'status_change' | 'note' | 'interview'
export type FollowUpState = 'overdue' | 'due_today' | 'upcoming'

export interface ApplicationJobSummary {
  id: string
  title: string | null
  company_name: string | null
  location: string | null
  remote_type: RemoteType
  source_url: string | null
}

export interface ApplicationMatchSummary {
  score_percent: number | null
  low_confidence: boolean
}

export interface Application {
  id: string
  job_posting_id: string
  status: ApplicationStatus
  notes: string | null
  applied_on: string | null
  next_action_text: string | null
  next_action_on: string | null
  follow_up_state: FollowUpState | null
  job: ApplicationJobSummary | null
  /** The posting's *current* match — the snapshot from when the user applied is on the event. */
  match: ApplicationMatchSummary | null
  /** The server owns the transition rules; the UI offers exactly what these say. */
  allowed_transitions: ApplicationStatus[]
  reopen_targets: ApplicationStatus[]
  created_at: string
  updated_at: string
}

/** What was known about the posting at the moment the user applied. Absent parts are null. */
export interface ApplySnapshot {
  captured_at: string
  match: { score_percent: number | null; assessed_weight: number; low_confidence: boolean } | null
  fraud_risk_level: FraudRiskLevel | null
  employer_verification: EmployerVerificationStatus | null
}

export interface ApplicationEvent {
  id: string
  event_type: ApplicationEventType
  from_status: ApplicationStatus | null
  to_status: ApplicationStatus | null
  occurred_on: string
  body: string | null
  snapshot: ApplySnapshot | null
  created_at: string
}

export interface ApplicationDetail extends Application {
  events: ApplicationEvent[]
}

export interface ApplicationStatusChangeInput {
  status: ApplicationStatus
  occurred_on?: string | null
  note?: string | null
}

export interface ApplicationEventInput {
  event_type: 'note' | 'interview'
  occurred_on?: string | null
  body: string
}

/** Only keys present are changed; an explicit null clears the field. */
export interface ApplicationPatch {
  notes?: string | null
  next_action_text?: string | null
  next_action_on?: string | null
}

export const applicationsApi = {
  list(token: string) {
    return apiFetch<Application[]>('/career/applications', { headers: authHeaders(token) })
  },
  get(token: string, id: string) {
    return apiFetch<ApplicationDetail>(`/career/applications/${id}`, { headers: authHeaders(token) })
  },
  create(token: string, jobPostingId: string) {
    return apiFetch<ApplicationDetail>('/career/applications', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ job_posting_id: jobPostingId }),
    })
  },
  changeStatus(token: string, id: string, input: ApplicationStatusChangeInput) {
    return apiFetch<ApplicationDetail>(`/career/applications/${id}/status`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  addEvent(token: string, id: string, input: ApplicationEventInput) {
    return apiFetch<ApplicationDetail>(`/career/applications/${id}/events`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(input),
    })
  },
  update(token: string, id: string, patch: ApplicationPatch) {
    return apiFetch<ApplicationDetail>(`/career/applications/${id}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify(patch),
    })
  },
  delete(token: string, id: string) {
    return apiFetch<void>(`/career/applications/${id}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    })
  },
}

// --- Career: resume tailoring ---

export type ResumeStatus = 'running' | 'completed' | 'failed'
export type ResumeChangeType = 'rewrite' | 'skills_order'
export type ResumeDecision = 'pending' | 'accepted' | 'rejected'

/** A posting requirement a change speaks to, with its verified quote from the posting. */
export interface ResumeAddress {
  requirement: string
  quote: string
}

export interface ResumeChange {
  id: string
  change_type: ResumeChangeType
  target_id: string
  target_label: string
  before_text: string
  after_text: string
  rationale: string
  addresses: ResumeAddress[]
  decision: ResumeDecision
  position: number
}

/** A skill the posting wants that the profile has no evidence for — shown, never written in. */
export interface ResumeGap {
  skill: string
  kind: 'required' | 'preferred'
  reason: string
}

/** A proposal discarded because it added claims the profile doesn't support. */
export interface ResumeDropped {
  source: string
  reason: string
}

export interface TailoredResume {
  id: string
  job_posting_id: string
  status: ResumeStatus
  error: string | null
  /** The profile changed after this draft was made. */
  is_stale: boolean
  started_at: string
  changes: ResumeChange[]
  gaps: ResumeGap[]
  dropped: ResumeDropped[]
  counts: { accepted: number; rejected: number; pending: number }
  /** The resume as it stands: original wording plus only the accepted changes. */
  preview_markdown: string
}

export interface ResumeExport {
  filename: string
  markdown: string
  accepted: number
  pending: number
  rejected: number
}

export const resumesApi = {
  /** null when no draft exists yet (a 404 here is the normal "not started" state). */
  async get(token: string, jobId: string): Promise<TailoredResume | null> {
    try {
      return await apiFetch<TailoredResume>(`/career/jobs/${jobId}/resume`, {
        headers: authHeaders(token),
      })
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
  tailor(token: string, jobId: string) {
    return apiFetch<{ status: string }>(`/career/jobs/${jobId}/tailor`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
  decide(token: string, resumeId: string, changeId: string, decision: ResumeDecision) {
    return apiFetch<TailoredResume>(`/career/resumes/${resumeId}/changes/${changeId}/decision`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ decision }),
    })
  },
  export(token: string, resumeId: string) {
    return apiFetch<ResumeExport>(`/career/resumes/${resumeId}/export`, {
      headers: authHeaders(token),
    })
  },
  delete(token: string, resumeId: string) {
    return apiFetch<void>(`/career/resumes/${resumeId}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    })
  },
}

// --- Career: cover letters ---

export type CoverRole = 'opening' | 'body' | 'closing'
export type CoverSupportType =
  | 'profile_experience'
  | 'profile_skill'
  | 'profile_summary'
  | 'posting_quote'

/** What a sentence was checked against: a role, an evidence-backed skill, the summary, or a
 * verbatim excerpt from the posting. */
export interface CoverSupport {
  type: CoverSupportType
  ref: string
  label: string
  excerpt: string
}

export interface CoverSentence {
  text: string
  /** "fact" was checked against its supports; "framing" carries no facts at all. */
  kind: 'fact' | 'framing'
  supports: CoverSupport[]
}

export interface CoverParagraph {
  id: string
  position: number
  role: CoverRole
  /** The fact-checked original. */
  text: string
  /** The user's own rewrite, if any — their words, so NOT fact-checked. */
  edited_text: string | null
  is_edited: boolean
  sentences: CoverSentence[]
  decision: ResumeDecision
}

/** A sentence discarded because the profile or posting didn't support it. */
export interface CoverDropped {
  sentence: string
  reason: string
}

export interface CoverLetter {
  id: string
  job_posting_id: string
  status: ResumeStatus
  error: string | null
  is_stale: boolean
  started_at: string
  paragraphs: CoverParagraph[]
  gaps: ResumeGap[]
  dropped: CoverDropped[]
  counts: { accepted: number; rejected: number; pending: number }
  /** The letter as it stands: accepted paragraphs only, using the user's edit where present. */
  preview_text: string
}

export interface CoverExport {
  filename: string
  text: string
  accepted: number
  pending: number
  rejected: number
  /** How many included paragraphs are the user's own wording, and so not fact-checked. */
  edited: number
}

export const coversApi = {
  /** null when no draft exists yet (a 404 here is the normal "not started" state). */
  async get(token: string, jobId: string): Promise<CoverLetter | null> {
    try {
      return await apiFetch<CoverLetter>(`/career/jobs/${jobId}/cover-letter`, {
        headers: authHeaders(token),
      })
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
  draft(token: string, jobId: string) {
    return apiFetch<{ status: string }>(`/career/jobs/${jobId}/cover-letter`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
  decide(token: string, letterId: string, paragraphId: string, decision: ResumeDecision) {
    return apiFetch<CoverLetter>(`/career/cover-letters/${letterId}/paragraphs/${paragraphId}/decision`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ decision }),
    })
  },
  /** text = null restores the fact-checked original. */
  edit(token: string, letterId: string, paragraphId: string, text: string | null) {
    return apiFetch<CoverLetter>(`/career/cover-letters/${letterId}/paragraphs/${paragraphId}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify({ text }),
    })
  },
  export(token: string, letterId: string) {
    return apiFetch<CoverExport>(`/career/cover-letters/${letterId}/export`, {
      headers: authHeaders(token),
    })
  },
  delete(token: string, letterId: string) {
    return apiFetch<void>(`/career/cover-letters/${letterId}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    })
  },
}

// --- Career: ATS compatibility check ---

export type AtsKeywordState = 'in_context' | 'listed_only' | 'gap'
export type AtsCheckStatus = 'pass' | 'warn' | 'fail'

export interface AtsKeyword {
  name: string
  kind: 'required' | 'preferred'
  state: AtsKeywordState
  detail: string
  /** For a skill only in the Skills list: roles whose evidence points at it. */
  roles: string[]
}

export interface AtsKeywordStats {
  required_found: number
  required_total: number
  preferred_found: number
  preferred_total: number
  in_context: number
  /** null when the posting listed no skills to check — never a made-up number. */
  coverage_percent: number | null
}

export interface AtsCheckItem {
  key: string
  label: string
  status: AtsCheckStatus
  detail: string
}

export interface AtsCheck {
  /** Which resume was checked: the tailored draft with accepted changes, or the profile-built one. */
  resume_source: 'tailored' | 'profile'
  accepted_changes: number
  keyword_stats: AtsKeywordStats
  keywords: AtsKeyword[]
  checks: AtsCheckItem[]
  summary: { passed: number; warn: number; fail: number }
  limitations: string[]
}

export interface AtsSafeExport {
  filename: string
  text: string
  resume_source: 'tailored' | 'profile'
  accepted_changes: number
}

export const atsApi = {
  check(token: string, jobId: string) {
    return apiFetch<AtsCheck>(`/career/jobs/${jobId}/ats-check`, {
      method: 'POST',
      headers: authHeaders(token),
    })
  },
  safeExport(token: string, jobId: string) {
    return apiFetch<AtsSafeExport>(`/career/jobs/${jobId}/ats-safe`, { headers: authHeaders(token) })
  },
}
