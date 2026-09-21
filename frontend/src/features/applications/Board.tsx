import type { Application, ApplicationStatus } from '@/lib/api'
import { ApplicationCard } from '@/features/applications/ApplicationCard'
import { ACTIVE_COLUMNS, CLOSED_STATUSES, STATUS_LABEL } from '@/features/applications/labels'

interface ColumnProps {
  title: string
  applications: Application[]
  selectedId: string | null
  onSelect: (id: string) => void
}

function Column({ title, applications, selectedId, onSelect }: ColumnProps) {
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-2 rounded-lg bg-muted/40 p-2">
      <h3 className="flex items-center justify-between px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
        <span className="tabular-nums">{applications.length}</span>
      </h3>
      {applications.length === 0 ? (
        <p className="px-1 py-3 text-xs text-muted-foreground">Nothing here.</p>
      ) : (
        applications.map((application) => (
          <ApplicationCard
            key={application.id}
            application={application}
            selected={selectedId === application.id}
            onSelect={onSelect}
          />
        ))
      )}
    </section>
  )
}

interface BoardProps {
  applications: Application[]
  selectedId: string | null
  onSelect: (id: string) => void
}

/** One column per pipeline stage, plus a final "Closed" column. Moving an application is done
 * from its detail panel (a form the keyboard and screen readers handle), not by dragging. */
export function Board({ applications, selectedId, onSelect }: BoardProps) {
  const byStatus = (statuses: ApplicationStatus[]) =>
    applications.filter((application) => statuses.includes(application.status))

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {ACTIVE_COLUMNS.map((status) => (
        <Column
          key={status}
          title={STATUS_LABEL[status]}
          applications={byStatus([status])}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
      <Column
        title="Closed"
        applications={byStatus(CLOSED_STATUSES)}
        selectedId={selectedId}
        onSelect={onSelect}
      />
    </div>
  )
}
