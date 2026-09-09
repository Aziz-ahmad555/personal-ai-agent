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
