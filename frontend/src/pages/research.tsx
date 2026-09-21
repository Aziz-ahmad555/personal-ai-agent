import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { NewQueryForm } from '@/features/research/NewQueryForm'
import { QueryHistoryList } from '@/features/research/QueryHistoryList'
import { QueryDetail } from '@/features/research/QueryDetail'

export function ResearchPage() {
  const [searchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('query'))
  const initialAnchor = searchParams.get('anchor')

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <NewQueryForm onCreated={setSelectedId} />
      <div className="grid items-start gap-6 md:grid-cols-[280px_1fr]">
        <QueryHistoryList selectedId={selectedId} onSelect={setSelectedId} />
        <QueryDetail
          queryId={selectedId}
          initialAnchor={selectedId === searchParams.get('query') ? initialAnchor : null}
        />
      </div>
    </div>
  )
}
