import { ChevronDown, ExternalLink, FileText } from 'lucide-react'

import { CitationFullPassage } from '@/components/chat/citation-full-passage'
import { CitationTable } from '@/components/chat/citation-table'
import type { CitationData } from '@/lib/api'

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

interface CitationDetailProps {
  citation: CitationData
  citationNumber: number
}

export function CitationDetail({ citation, citationNumber }: CitationDetailProps) {
  const location = [
    citation.pageNumber ? `Page ${citation.pageNumber}` : null,
    citation.sectionTitle,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.15em] text-muted-foreground uppercase">
          <FileText className="size-3.5" aria-hidden="true" />
          Source {citationNumber}
        </div>
        <h3 className="font-heading text-2xl leading-tight">{citation.company}</h3>
        <p className="text-sm text-muted-foreground">
          {citation.ticker} · {citation.filingType}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-4 border-y py-5 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Filed</dt>
          <dd className="mt-1 font-medium">
            {dateFormatter.format(new Date(`${citation.filingDate}T00:00:00`))}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Report date</dt>
          <dd className="mt-1 font-medium">
            {dateFormatter.format(new Date(`${citation.reportDate}T00:00:00`))}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-xs text-muted-foreground">Location</dt>
          <dd className="mt-1 font-medium">{location || `Chunk ${citation.chunkIndex}`}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-xs text-muted-foreground">Accession number</dt>
          <dd className="mt-1 break-all font-mono text-xs">{citation.accessionNumber}</dd>
        </div>
      </dl>

      <div className="space-y-2">
        <p className="text-xs font-semibold tracking-[0.15em] text-muted-foreground uppercase">
          Exact excerpt
        </p>
        {citation.passage?.kind === 'table' ? (
          <CitationTable focusExcerpt passage={citation.passage} />
        ) : (
          <blockquote className="border-l-2 border-primary bg-muted/50 px-4 py-3 text-sm leading-6">
            {citation.excerpt}
          </blockquote>
        )}
      </div>

      {citation.passage ? (
        <details className="group border-y py-1" key={citation.citationId}>
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 py-3 text-sm font-semibold focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
            Full source passage
            <ChevronDown
              className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden="true"
            />
          </summary>
          <div className="pb-4">
            <CitationFullPassage passage={citation.passage} />
          </div>
        </details>
      ) : null}

      <a
        className="inline-flex items-center gap-2 text-sm font-semibold underline decoration-border underline-offset-4 hover:decoration-foreground focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-offset-4"
        href={citation.secUrl}
        rel="noreferrer"
        target="_blank"
      >
        Open SEC filing
        <ExternalLink className="size-3.5" aria-hidden="true" />
      </a>
    </div>
  )
}
