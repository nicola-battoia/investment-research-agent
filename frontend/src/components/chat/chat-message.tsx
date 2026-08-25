import { Ban, BookOpenCheck, SearchX } from 'lucide-react'
import type { ReactNode } from 'react'

import type { AnswerStatus, ChatMessage, CitationData } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ChatMessageProps {
  citationNumbers: ReadonlyMap<string, number>
  message: ChatMessage
  onCitationSelect: (citation: CitationData, trigger: HTMLButtonElement) => void
  selectedCitationId?: string
}

export function ChatMessageView({
  citationNumbers,
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
        (answerStatus === 'investment_advice_refused' ||
          answerStatus === 'out_of_scope') &&
          'border-slate-400',
        (!answerStatus ||
          answerStatus === 'supported' ||
          answerStatus === 'conversational') &&
          'border-transparent pl-0',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[0.65rem] font-semibold tracking-[0.18em] text-muted-foreground uppercase">
          Document Copilot
        </p>
        {answerStatus &&
        answerStatus !== 'supported' &&
        answerStatus !== 'conversational' ? (
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
              citationNumbers,
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

type LabeledAnswerStatus = Exclude<
  AnswerStatus,
  'conversational' | 'supported'
>

function AnswerStatusLabel({ status }: { status: LabeledAnswerStatus }) {
  const insufficient = status === 'insufficient_evidence'
  const label =
    status === 'insufficient_evidence'
      ? 'Insufficient filing evidence'
      : status === 'investment_advice_refused'
        ? 'Investment advice declined'
        : 'Outside filing research scope'
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
      {label}
    </span>
  )
}

function renderCitedText(
  text: string,
  citations: Map<string, CitationData>,
  citationNumbers: ReadonlyMap<string, number>,
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
      const citationNumber =
        citationNumbers.get(citation.citationId) ?? citation.citationIndex + 1
      nodes.push(
        <button
          aria-label={`Open source ${citationNumber}: ${citation.company} ${citation.filingType}`}
          aria-pressed={selectedCitationId === citation.citationId}
          className="mx-0.5 inline-flex min-w-5 translate-y-[-0.05em] items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[0.68rem] font-bold leading-none text-primary-foreground outline-none hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-ring/50"
          key={`${citation.citationId}-${match.index}`}
          onClick={(event) => onCitationSelect(citation, event.currentTarget)}
          type="button"
        >
          {citationNumber}
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
