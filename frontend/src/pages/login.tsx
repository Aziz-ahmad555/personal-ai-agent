import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { useAuthStore } from '@/stores/auth'
import { isDemoMode } from '@/lib/demo'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const demoLogin = useAuthStore((s) => s.demoLogin)
  const isAuthenticating = useAuthStore((s) => s.isAuthenticating)
  const error = useAuthStore((s) => s.error)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch {
      // Failure is surfaced via the store's `error` field below.
    }
  }

  async function handleDemoLogin() {
    try {
      await demoLogin()
      navigate('/dashboard')
    } catch {
      // Failure is surfaced via the store's `error` field below.
    }
  }

  if (isDemoMode) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-4">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
        >
          <Card className="w-full max-w-sm">
            <CardHeader>
              <CardTitle>Personal AI Agent — Demo</CardTitle>
              <CardDescription>
                You're about to sign in as a sample account with pre-loaded data. Nothing you see
                connects to a real Gmail, GitHub, or Calendar account, and no real emails or
                applications are ever sent.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {error && <ErrorState message={error} />}
              <Button onClick={handleDemoLogin} className="w-full" disabled={isAuthenticating}>
                {isAuthenticating ? 'Signing in…' : 'View the demo'}
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Access your Personal AI Agent.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {error && <ErrorState message={error} />}
              <Button type="submit" className="w-full" disabled={isAuthenticating}>
                {isAuthenticating ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  )
}
