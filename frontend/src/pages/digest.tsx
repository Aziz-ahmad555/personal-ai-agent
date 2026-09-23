import { DigestPanel } from '@/features/reporting/DigestPanel'

export function DigestPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <h1 className="text-xl font-semibold">Weekly Digest</h1>
      <DigestPanel />
    </div>
  )
}
