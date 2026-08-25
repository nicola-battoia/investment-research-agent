import { CitationTable } from '@/components/chat/citation-table'
import type { CitationTextHighlight, CitationPassage } from '@/lib/api'

interface CitationFullPassageProps {
  passage: CitationPassage
}

export function CitationFullPassage({ passage }: CitationFullPassageProps) {
  if (passage.kind === 'table') {
    return <CitationTable passage={passage} />
  }

  return (
    <p className="max-h-[60vh] overflow-auto rounded-md border bg-background p-4 text-sm leading-6 whitespace-pre-wrap">
      {highlightedText(passage.text, passage.highlights)}
    </p>
  )
}

function highlightedText(text: string, highlights: CitationTextHighlight[]) {
  const merged = [...highlights]
    .sort((left, right) => left.start - right.start)
    .reduce<CitationTextHighlight[]>((ranges, highlight) => {
      const previous = ranges.at(-1)
      if (previous && highlight.start <= previous.end) {
        previous.end = Math.max(previous.end, highlight.end)
      } else {
        ranges.push({ ...highlight })
      }
      return ranges
    }, [])
  const parts = []
  let cursor = 0
  for (const highlight of merged) {
    parts.push(text.slice(cursor, highlight.start))
    parts.push(
      <mark
        className="rounded-sm bg-primary/20 px-0.5 font-medium text-foreground ring-1 ring-primary/30"
        key={`${highlight.start}-${highlight.end}`}
      >
        {text.slice(highlight.start, highlight.end)}
      </mark>,
    )
    cursor = highlight.end
  }
  parts.push(text.slice(cursor))
  return parts
}
