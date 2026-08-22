import { BookOpen, PanelRightClose } from 'lucide-react'
import { useEffect, useState } from 'react'

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

interface CitationPanelProps {
  citation: CitationData | null
  onClose: () => void
}

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  const [isDesktop, setIsDesktop] = useState(() =>
    window.matchMedia('(min-width: 80rem)').matches,
  )

  useEffect(() => {
    const media = window.matchMedia('(min-width: 80rem)')
    const update = () => setIsDesktop(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  return (
    <>
      <aside
        className="hidden w-88 shrink-0 overflow-y-auto border-l bg-muted/20 xl:block"
        aria-label="Citation source"
      >
        {citation ? (
          <div className="relative p-7">
            <Button
              aria-label="Close citation source"
              className="absolute top-5 right-5"
              onClick={onClose}
              size="icon-xs"
              variant="ghost"
            >
              <PanelRightClose aria-hidden="true" />
            </Button>
            <CitationDetail citation={citation} />
          </div>
        ) : (
          <div className="grid min-h-full place-items-center px-8 py-12 text-center">
            <div className="space-y-3 text-muted-foreground">
              <BookOpen className="mx-auto size-5" aria-hidden="true" />
              <p className="text-xs leading-5">
                Select a numbered source in an answer to inspect the exact filing passage.
              </p>
            </div>
          </div>
        )}
      </aside>

      <Sheet
        open={!isDesktop && citation !== null}
        onOpenChange={(open) => {
          if (!open) onClose()
        }}
      >
        <SheetContent className="w-[min(92vw,28rem)] overflow-y-auto" side="right">
          <SheetHeader className="border-b px-6 py-5 pr-14">
            <SheetTitle>Filing source</SheetTitle>
            <SheetDescription>Verify the answer against the cited passage.</SheetDescription>
          </SheetHeader>
          {citation ? (
            <div className="p-6">
              <CitationDetail citation={citation} />
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </>
  )
}
