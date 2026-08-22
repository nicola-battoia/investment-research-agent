import { Ban, BookOpenCheck, SearchX } from 'lucide-react'
import type { ReactNode } from 'react'

import type { AnswerStatus, ChatMessage, CitationData } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ChatMessageProps {
  message: ChatMessage
  onCitationSelect: (citation: CitationData, trigger: HTMLButtonElement) => void
  selectedCitationId?: string
}

export function ChatMessageView({
  message,
  onCitationSelect,
  selectedCitationId,
}: ChatMessageProps) {
  const citations = message.parts
    .filter((part) => part.type === 'data-citation')
    .map((part) => part.data)
  const citationBySource = new Map(
    citations.map((citation) => [citation.sourceId, citation]),
  )
  const answerStatus = message.metadata?.answerStatus

  if (message.role === 'user') {
    return (
      <article className="ml-auto max-w-[88%] border-l-2 border-primary bg-muted/60 px-4 py-3 sm:max-w-[80%]">
        <p className="mb-1 text-[0.65rem] font-semibold tracking-[0.18em] text-muted-foreground uppercase">
          You
        </p>
        {message.parts.map((part, index) =>
          part.type === 'text' ? (
            <p
              key={`${message.id}-${index}`}
              className="whitespace-pre-wrap text-sm leading-7"
            >
              {part.text}
            </p>
          ) : null,
        )}
      </article>
    )
  }

  return (
    <article
      className={cn(
        'max-w-3xl space-y-3 border-l-2 pl-4',
        answerStatus === 'insufficient_evidence' && 'border-amber-500/70',
        answerStatus === 'investment_advice_refused' && 'border-slate-400',
        (!answerStatus || answerStatus === 'supported') && 'border-transparent pl-0',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[0.65rem] font-semibold tracking-[0.18em] text-muted-foreground uppercase">
          Document Copilot
        </p>
        {answerStatus && answerStatus !== 'supported' ? (
          <AnswerStatusLabel status={answerStatus} />
        ) : null}
      </div>

      {message.parts.map((part, index) =>
        part.type === 'text' ? (
          <div
            key={`${message.id}-${index}`}
            className="whitespace-pre-wrap text-sm leading-7 sm:text-[0.95rem]"
          >
            {renderCitedText(
              part.text,
              citationBySource,
              selectedCitationId,
              onCitationSelect,
            )}
          </div>
        ) : null,
      )}

      {citations.length > 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <BookOpenCheck className="size-3.5" aria-hidden="true" />
          {citations.length} verified {citations.length === 1 ? 'source' : 'sources'}
        </p>
      ) : null}
    </article>
  )
}

function AnswerStatusLabel({ status }: { status: Exclude<AnswerStatus, 'supported'> }) {
  const insufficient = status === 'insufficient_evidence'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.65rem] font-semibold',
        insufficient
          ? 'bg-amber-500/10 text-amber-800'
          : 'bg-slate-500/10 text-slate-700',
      )}
    >
      {insufficient ? (
        <SearchX className="size-3" aria-hidden="true" />
      ) : (
        <Ban className="size-3" aria-hidden="true" />
      )}
      {insufficient ? 'Insufficient filing evidence' : 'Investment advice declined'}
    </span>
  )
}

function renderCitedText(
  text: string,
  citations: Map<string, CitationData>,
  selectedCitationId: string | undefined,
  onCitationSelect: (citation: CitationData, trigger: HTMLButtonElement) => void,
): ReactNode[] {
  const nodes: ReactNode[] = []
  const marker = /\[(S[1-9][0-9]*)\]/g
  let offset = 0
  let match: RegExpExecArray | null

  while ((match = marker.exec(text)) !== null) {
    if (match.index > offset) nodes.push(text.slice(offset, match.index))
    const citation = citations.get(match[1])
    if (citation) {
      nodes.push(
        <button
          aria-label={`Open source ${citation.citationIndex + 1}: ${citation.company} ${citation.filingType}`}
          aria-pressed={selectedCitationId === citation.citationId}
          className="mx-0.5 inline-flex min-w-5 translate-y-[-0.05em] items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[0.68rem] font-bold leading-none text-primary-foreground outline-none hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring/50"
          key={`${citation.citationId}-${match.index}`}
          onClick={(event) => onCitationSelect(citation, event.currentTarget)}
          type="button"
        >
          {citation.citationIndex + 1}
        </button>,
      )
    } else {
      nodes.push(match[0])
    }
    offset = marker.lastIndex
  }
  if (offset < text.length) nodes.push(text.slice(offset))
  return nodes
}
