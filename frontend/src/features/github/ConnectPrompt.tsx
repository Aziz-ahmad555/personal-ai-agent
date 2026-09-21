import { Github } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { useStartGithubOAuth } from '@/features/github/hooks'

export function ConnectPrompt({ reconnect = false }: { reconnect?: boolean }) {
  const start = useStartGithubOAuth()
  const label = reconnect ? 'Reconnect GitHub' : 'Connect GitHub (read-only)'

  return (
    <Card>
      <CardHeader>
        <CardTitle>{reconnect ? 'Reconnect GitHub' : 'Connect GitHub'}</CardTitle>
        <CardDescription>Read-only, and only what&apos;s described below. Nothing else.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-3 rounded-md border border-border p-4 text-sm">
          <Github className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
          <div className="space-y-3 text-muted-foreground">
            <p>
              You sign in on github.com and authorize a GitHub App that has{' '}
              <span className="text-foreground">no permissions</span> beyond reading public
              information. This proves which account is yours; it doesn&apos;t grant access to anything
              private.
            </p>
            <div>
              <p className="font-medium text-foreground">It can</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Read your profile and your public repositories.</li>
              </ul>
            </div>
            <div>
              <p className="font-medium text-foreground">It cannot</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Write anything: no commits, issues, comments, stars, forks or settings.</li>
                <li>See private repositories, organisations you belong to, or your email address.</li>
                <li>Act on its own: connecting and disconnecting are the only things that happen here.</li>
              </ul>
            </div>
            <p>You can disconnect at any time. That revokes the token on GitHub and clears it here.</p>
            <p className="rounded-md bg-muted p-3">
              <span className="font-medium text-foreground">Not built yet:</span> importing your
              repositories as profile evidence, and the recruiter-readiness review. For now, connecting
              only links your account.
            </p>
          </div>
        </div>

        {start.isError && (
          <ErrorState
            title="Couldn't start the connection"
            message={start.error instanceof Error ? start.error.message : 'Failed to start connection'}
          />
        )}

        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          <Github className="h-4 w-4" />
          {start.isPending ? 'Redirecting…' : label}
        </Button>
      </CardContent>
    </Card>
  )
}
