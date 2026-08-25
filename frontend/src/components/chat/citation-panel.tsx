import { BookOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { CitationDetail } from '@/components/chat/citation-detail'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import type { CitationData } from '@/lib/api'
import { cn } from '@/lib/utils'

interface CitationPanelProps {
  citation: CitationData | null
  citationNumber: number | null
  desktopOpen: boolean
  onClose: () => void
  onDesktopOpenChange: (open: boolean) => void
}

export function CitationPanel({
  citation,
  citationNumber,
  desktopOpen,
  onClose,
  onDesktopOpenChange,
}: CitationPanelProps) {
  const desktopPanelRef = useRef<HTMLDivElement>(null)
  const mobilePanelRef = useRef<HTMLDivElement>(null)
  const [isDesktop, setIsDesktop] = useState(() =>
    window.matchMedia('(min-width: 80rem)').matches,
  )

  useEffect(() => {
    const media = window.matchMedia('(min-width: 80rem)')
    const update = () => setIsDesktop(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    desktopPanelRef.current?.scrollTo({ top: 0 })
    mobilePanelRef.current?.scrollTo({ top: 0 })
  }, [citation?.citationId])
  const hasTable = citation?.passage?.kind === 'table'

  return (
    <>
      <aside
        className={cn(
          'hidden h-full min-h-0 shrink-0 overflow-hidden border-l bg-muted/20 transition-[width] duration-200 motion-reduce:transition-none xl:flex',
          desktopOpen
            ? hasTable
              ? 'w-[clamp(22rem,38vw,40rem)]'
              : 'w-88'
            : 'w-12',
        )}
        aria-label="Sources sidebar"
      >
        {desktopOpen ? (
          <div className="flex h-full min-h-0 w-full flex-col">
            <header className="flex shrink-0 items-start justify-between gap-4 border-b px-6 py-5">
              <div>
                <h2 className="font-heading text-lg">Sources</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {citation ? 'Filing evidence for the selected citation.' : 'Select a citation to inspect its filing evidence.'}
                </p>
              </div>
              <Button
                aria-label="Hide sources sidebar"
                onClick={() => onDesktopOpenChange(false)}
                size="icon-sm"
                variant="ghost"
              >
                <PanelRightClose aria-hidden="true" />
              </Button>
            </header>
            <div
              ref={desktopPanelRef}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
            >
              {citation && citationNumber !== null ? (
                <div className="p-7">
                  <CitationDetail
                    citation={citation}
                    citationNumber={citationNumber}
                  />
                </div>
              ) : (
                <div className="grid min-h-full place-items-center px-8 py-12 text-center">
                  <div className="space-y-3 text-muted-foreground">
                    <BookOpen className="mx-auto size-5" aria-hidden="true" />
                    <p className="text-xs leading-5">
                      Select a numbered source in an answer to inspect the exact filing
                      passage.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full w-full flex-col items-center py-3">
            <Button
              aria-label="Show sources sidebar"
              onClick={() => onDesktopOpenChange(true)}
              size="icon-sm"
              variant="ghost"
            >
              <PanelRightOpen aria-hidden="true" />
            </Button>
          </div>
        )}
      </aside>

      <Sheet
        open={!isDesktop && citation !== null}
        onOpenChange={(open) => {
          if (!open) onClose()
        }}
      >
        <SheetContent
          ref={mobilePanelRef}
          className={cn(
            'overflow-y-auto',
            hasTable
              ? 'data-[side=right]:w-[min(96vw,42rem)] data-[side=right]:sm:max-w-[42rem]'
              : 'data-[side=right]:w-[min(92vw,28rem)]',
          )}
          side="right"
        >
          <SheetHeader className="border-b px-6 py-5 pr-14">
            <SheetTitle>Filing source</SheetTitle>
            <SheetDescription>Verify the answer against the cited passage.</SheetDescription>
          </SheetHeader>
          {citation && citationNumber !== null ? (
            <div className="p-6">
              <CitationDetail citation={citation} citationNumber={citationNumber} />
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </>
  )
}
