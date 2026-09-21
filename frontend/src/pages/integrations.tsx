import { Link } from 'react-router-dom'
import { Ban } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { Integration } from '@/lib/api'
import { useIntegrations } from '@/features/integrations/hooks'

const STATUS_LABEL: Record<Integration['status'], string> = {
  connected: 'Connected',
  needs_reauth: 'Needs reconnect',
  disconnected: 'Disconnected',
  not_connected: 'Not connected',
  unavailable: 'Unavailable',
}

export function IntegrationCard({ integration }: { integration: Integration }) {
  const unavailable = integration.status === 'unavailable'
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base">{integration.label}</CardTitle>
          <CardDescription>{integration.summary}</CardDescription>
        </div>
        {unavailable ? (
          <Badge variant="outline" className="shrink-0 gap-1 whitespace-nowrap text-muted-foreground">
            <Ban className="h-3 w-3" /> {STATUS_LABEL.unavailable}
          </Badge>
        ) : (
          <Badge
            variant={integration.status === 'connected' ? 'default' : 'outline'}
            className="shrink-0 whitespace-nowrap"
          >
            {STATUS_LABEL[integration.status]}
          </Badge>
        )}
      </CardHeader>
      <CardContent>
        {unavailable ? (
          <p className="text-sm text-muted-foreground">{integration.reason}</p>
        ) : (
          integration.path && (
            <Button asChild variant="outline" size="sm">
              <Link to={integration.path}>
                {integration.status === 'connected' ? 'Open' : 'Set up'} {integration.label}
              </Link>
            </Button>
          )
        )}
      </CardContent>
    </Card>
  )
}

export function IntegrationsPage() {
  const { data, isLoading, isError, error, refetch } = useIntegrations()

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Integrations</h1>
        <p className="text-sm text-muted-foreground">
          What the agent is connected to. Every connection is read-only for now, and only official APIs
          are used.
        </p>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}

      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : 'Failed to load integrations'}
          onRetry={() => refetch()}
        />
      )}

      {data && (
        <div className="space-y-3">
          {data.map((integration) => (
            <IntegrationCard key={integration.key} integration={integration} />
          ))}
        </div>
      )}
    </div>
  )
}
