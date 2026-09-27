import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi, configureAuthHooks, type UserRead } from '@/lib/api'

interface AuthState {
  accessToken: string | null
  refreshToken: string | null
  user: UserRead | null
  isAuthenticating: boolean
  error: string | null
  login: (email: string, password: string) => Promise<void>
  demoLogin: () => Promise<void>
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticating: false,
      error: null,

      login: async (email, password) => {
        set({ isAuthenticating: true, error: null })
        try {
          const tokens = await authApi.login(email, password)
          const user = await authApi.me(tokens.access_token)
          set({
            accessToken: tokens.access_token,
            refreshToken: tokens.refresh_token,
            user,
            isAuthenticating: false,
          })
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Login failed'
          set({ isAuthenticating: false, error: message })
          throw err
        }
      },

      demoLogin: async () => {
        set({ isAuthenticating: true, error: null })
        try {
          const tokens = await authApi.demoLogin()
          const user = await authApi.me(tokens.access_token)
          set({
            accessToken: tokens.access_token,
            refreshToken: tokens.refresh_token,
            user,
            isAuthenticating: false,
          })
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Could not start the demo'
          set({ isAuthenticating: false, error: message })
          throw err
        }
      },

      logout: () => set({ accessToken: null, refreshToken: null, user: null, error: null }),
    }),
    {
      name: 'personal-agent-auth',
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    }
  )
)

// Wire token refresh into every API call. Kept here (not in api.ts) because the store already
// imports api.ts; a 401 that survives a refresh signs the user out, and ProtectedRoute then
// sends them to /login.
configureAuthHooks({
  getRefreshToken: () => useAuthStore.getState().refreshToken,
  onRefreshed: (tokens) =>
    useAuthStore.setState({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
    }),
  onExpired: () => useAuthStore.getState().logout(),
})
