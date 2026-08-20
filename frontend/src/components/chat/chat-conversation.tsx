import { useChat } from '@ai-sdk/react'
import { LoaderCircle, Send } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { ChatMessage } from '@/lib/api'
import { createChatTransport } from '@/lib/chat-transport'
import { userFacingError } from '@/lib/user-facing-error'

interface ChatConversationProps {
  initialMessages: ChatMessage[]
  onTurnFinished: () => void
  threadId: string
}

export function ChatConversation({
  initialMessages,
  onTurnFinished,
  threadId,
}: ChatConversationProps) {
  const [input, setInput] = useState('')
  const transport = useMemo(() => createChatTransport(), [])
  const endRef = useRef<HTMLDivElement>(null)
  const {
    clearError,
    error,
    messages,
    sendMessage,
    status,
  } = useChat<ChatMessage>({
    id: threadId,
    messages: initialMessages,
    onFinish: onTurnFinished,
    transport,
  })
  const isStreaming = status === 'submitted' || status === 'streaming'

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status])

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = input.trim()
    if (!message || isStreaming) return
    clearError()
    setInput('')
    void sendMessage({ text: message })
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-5 py-8 sm:px-8">
          {messages.length === 0 ? (
            <div className="my-auto space-y-3 py-16 text-center">
              <p className="text-xs font-semibold tracking-[0.2em] text-muted-foreground uppercase">
                New conversation
              </p>
              <h2 className="font-heading text-3xl">Ask about the filing corpus</h2>
              <p className="mx-auto max-w-lg text-sm leading-6 text-muted-foreground">
                This phase uses a temporary assistant response while proving secure,
                persisted chat delivery.
              </p>
            </div>
          ) : (
            <div className="space-y-7">
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={
                    message.role === 'user'
                      ? 'ml-auto max-w-[85%] border-l-2 border-primary bg-muted/60 px-4 py-3'
                      : 'max-w-2xl space-y-2'
                  }
                >
                  <p className="text-[0.65rem] font-semibold tracking-[0.18em] text-muted-foreground uppercase">
                    {message.role === 'user' ? 'You' : 'Document Copilot'}
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
              ))}
              {isStreaming ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />
                  Document Copilot is responding…
                </div>
              ) : null}
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t bg-background px-5 py-4 sm:px-8">
        <form
          className="mx-auto flex max-w-3xl items-end gap-3 border bg-muted/30 px-4 shadow-sm"
          onSubmit={handleSubmit}
        >
          <Textarea
            aria-label="Message Document Copilot"
            className="max-h-40 min-h-14 flex-1 border-0 py-4 focus-visible:border-0"
            disabled={isStreaming}
            maxLength={10_000}
            onChange={(event) => setInput(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder="Ask a question about a filing…"
            value={input}
          />
          <Button
            aria-label="Send message"
            className="mb-2"
            disabled={!input.trim() || isStreaming}
            size="icon-sm"
            type="submit"
          >
            {isStreaming ? (
              <LoaderCircle className="animate-spin" aria-hidden="true" />
            ) : (
              <Send aria-hidden="true" />
            )}
          </Button>
        </form>
        {error ? (
          <div
            className="mx-auto mt-3 flex max-w-3xl items-center justify-between gap-4 text-sm text-destructive"
            role="alert"
          >
            <span>{userFacingError(error)}</span>
            <Button type="button" variant="ghost" size="xs" onClick={clearError}>
              Dismiss
            </Button>
          </div>
        ) : null}
      </div>
    </section>
  )
}
