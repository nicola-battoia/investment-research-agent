import { LoaderCircle, Send, Square } from 'lucide-react'
import { useEffect, useRef, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface ChatComposerProps {
  input: string
  isRunning: boolean
  onInputChange: (value: string) => void
  onStop: () => void
  onSubmit: () => void
}

export function ChatComposer({
  input,
  isRunning,
  onInputChange,
  onStop,
  onSubmit,
}: ChatComposerProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!isRunning) inputRef.current?.focus()
  }, [isRunning])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!input.trim() || isRunning) return
    onSubmit()
  }

  return (
    <form
      className="flex items-end gap-3 border bg-muted/30 px-4 shadow-sm focus-within:border-ring"
      onSubmit={handleSubmit}
    >
      <Textarea
        ref={inputRef}
        aria-label="Message Document Copilot"
        className="max-h-40 min-h-14 flex-1 border-0 py-4 focus-visible:border-0"
        disabled={isRunning}
        maxLength={10_000}
        onChange={(event) => onInputChange(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            event.currentTarget.form?.requestSubmit()
          }
        }}
        placeholder="Ask a question about a filing…"
        value={input}
      />
      {isRunning ? (
        <Button
          aria-label="Stop response"
          className="mb-2"
          onClick={onStop}
          size="icon-sm"
          type="button"
          variant="outline"
        >
          <Square className="size-3 fill-current" aria-hidden="true" />
        </Button>
      ) : (
        <Button
          aria-label="Send message"
          className="mb-2"
          disabled={!input.trim()}
          size="icon-sm"
          type="submit"
        >
          <Send aria-hidden="true" />
        </Button>
      )}
      <span className="sr-only" aria-live="polite">
        {isRunning ? (
          <span className="flex items-center gap-1">
            <LoaderCircle className="animate-spin" aria-hidden="true" />
            Preparing response
          </span>
        ) : null}
      </span>
    </form>
  )
}
