import { useLayoutEffect, useRef } from 'react'

import type { TableCitationPassage } from '@/lib/api'
import { cn } from '@/lib/utils'

interface CitationTableProps {
  focusExcerpt?: boolean
  passage: TableCitationPassage
}

export function CitationTable({ focusExcerpt = false, passage }: CitationTableProps) {
  const viewportRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!focusExcerpt) return
    const viewport = viewportRef.current
    const highlightedCell = viewport?.querySelector<HTMLElement>(
      '[data-citation-highlight="true"]',
    )
    if (!viewport || !highlightedCell) return

    const viewportBounds = viewport.getBoundingClientRect()
    const cellBounds = highlightedCell.getBoundingClientRect()
    viewport.scrollTop +=
      cellBounds.top -
      viewportBounds.top -
      (viewport.clientHeight - cellBounds.height) / 2
    viewport.scrollLeft +=
      cellBounds.left -
      viewportBounds.left -
      (viewport.clientWidth - cellBounds.width) / 2
  }, [focusExcerpt, passage])

  return (
    <div
      ref={viewportRef}
      className={cn(
        'overscroll-contain rounded-md border bg-background focus-visible:outline-2 focus-visible:outline-offset-2',
        focusExcerpt ? 'max-h-72' : 'max-h-[60vh]',
        'overflow-auto',
      )}
      tabIndex={0}
    >
      <table
        aria-colcount={passage.columnCount}
        className="w-max min-w-full border-separate border-spacing-0 text-left text-xs [font-variant-numeric:tabular-nums]"
      >
        <caption className="sr-only">
          {focusExcerpt ? 'Citation table focused on cited cells' : 'Full citation table'}
        </caption>
        <tbody>
          {passage.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.cells.map((cell, cellIndex) => {
                const cellClassName = cn(
                  'align-top leading-5',
                  cell.text
                    ? 'min-w-14 max-w-64 border-r border-b px-2.5 py-1.5 whitespace-normal'
                    : 'w-0 min-w-0 border-0 p-0 text-[0px] leading-none',
                  (cell.columnHeader || cell.rowHeader) &&
                    cell.text &&
                    'bg-muted/70 font-semibold',
                  cellIndex === 0 && cell.text && 'sticky left-0 z-30 bg-background',
                  cellIndex === 0 &&
                    cell.text &&
                    (cell.columnHeader || cell.rowHeader) &&
                    'bg-muted',
                  cell.highlighted &&
                    'bg-[color-mix(in_oklab,var(--primary)_20%,var(--background))] font-semibold text-foreground ring-1 ring-inset ring-primary/50',
                )
                const sharedProps = {
                  'aria-colindex': cell.columnIndex + 1,
                  className: cellClassName,
                  colSpan: cell.columnSpan,
                  'data-citation-highlight': cell.highlighted ? 'true' : undefined,
                  rowSpan: cell.rowSpan,
                }

                if (cell.columnHeader || cell.rowHeader) {
                  return (
                    <th
                      key={`${cell.columnIndex}-${cellIndex}`}
                      {...sharedProps}
                      scope={cell.columnHeader ? 'col' : 'row'}
                    >
                      {cell.text || null}
                    </th>
                  )
                }
                return (
                  <td key={`${cell.columnIndex}-${cellIndex}`} {...sharedProps}>
                    {cell.text || null}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
