import { useChat } from '@ai-sdk/react'
import { CircleAlert, LoaderCircle, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ChatComposer } from '@/components/chat/chat-composer'
import { ChatMessageView } from '@/components/chat/chat-message'
import { CitationPanel } from '@/components/chat/citation-panel'
import { Button } from '@/components/ui/button'
import {
  api,
  type ChatMessage,
  type CitationData,
  type TurnErrorData,
  type TurnStatusData,
} from '@/lib/api'
import { createChatTransport } from '@/lib/chat-transport'
import { useAuth } from '@/lib/auth'
import { ApiError } from '@/lib/http'
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
  const { signOut } = useAuth()
  const [input, setInput] = useState('')
  const [selectedCitation, setSelectedCitation] = useState<CitationData | null>(null)
  const [turnStatus, setTurnStatus] = useState<TurnStatusData | null>(null)
  const [turnFailure, setTurnFailure] = useState<TurnErrorData | null>(null)
  const [failedUserId, setFailedUserId] = useState<string | null>(null)
  const transport = useMemo(() => createChatTransport(), [])
  const endRef = useRef<HTMLDivElement>(null)
  const citationTriggerRef = useRef<HTMLButtonElement | null>(null)
  const pendingTextRef = useRef('')
  const {
    clearError,
    error,
    messages,
    regenerate,
    sendMessage,
    setMessages,
    status,
    stop,
  } = useChat<ChatMessage>({
    id: threadId,
    messages: initialMessages,
    onData: (part) => {
      if (part.type === 'data-turn-status') setTurnStatus(part.data)
      if (part.type === 'data-turn-error') setTurnFailure(part.data)
    },
    onFinish: ({ isAbort, isDisconnect, isError, messages: finishedMessages }) => {
      setTurnStatus(null)
      const lastUser = [...finishedMessages]
        .reverse()
        .find((message) => message.role === 'user')

      if (isAbort) {
        const restoredText = lastUser ? messageText(lastUser) : pendingTextRef.current
        setInput(restoredText)
        if (lastUser) {
          setMessages((current) =>
            current.filter((message) => message.id !== lastUser.id),
          )
        }
        setTurnFailure(null)
        setFailedUserId(null)
        return
      }

      if (isError || isDisconnect) {
        if (lastUser) {
          setFailedUserId(lastUser.id)
          void reconcileCommittedTurn(lastUser.id)
        }
        return
      }

      setTurnFailure(null)
      setFailedUserId(null)
      pendingTextRef.current = ''
      onTurnFinished()
    },
    transport,
  })
  const isRunning = status === 'submitted' || status === 'streaming'

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status])

  async function reconcileCommittedTurn(clientMessageId: string) {
    try {
      const detail = await api.getThread(threadId)
      if (!detail.messages.some((message) => message.id === clientMessageId)) return
      setMessages(detail.messages)
      clearError()
      setTurnFailure(null)
      setFailedUserId(null)
      pendingTextRef.current = ''
      onTurnFinished()
    } catch {
      // The original stream error remains the actionable message for the user.
    }
  }

  function handleSubmit() {
    const message = input.trim()
    if (!message || isRunning) return
    clearError()
    setTurnFailure(null)
    setTurnStatus(null)
    setFailedUserId(null)
    pendingTextRef.current = message
    setInput('')
    void sendMessage({ text: message })
  }

  function handleRetry() {
    if (!failedUserId || isRunning) return
    clearError()
    setTurnFailure(null)
    setTurnStatus(null)
    void regenerate({ messageId: failedUserId })
  }

  function closeCitation() {
    setSelectedCitation(null)
    window.setTimeout(() => citationTriggerRef.current?.focus(), 0)
  }

  const errorMessage = turnFailure?.message ?? (error ? userFacingError(error) : null)
  const retryable = turnFailure?.retryable ?? isRetryableError(error)
  const sessionExpired = error instanceof ApiError && error.status === 401

  return (
    <section className="flex min-h-0 flex-1 bg-background">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col px-5 py-8 sm:px-8 lg:px-12">
            {messages.length === 0 ? (
              <div className="my-auto space-y-4 py-16 text-center">
                <p className="text-xs font-semibold tracking-[0.2em] text-muted-foreground uppercase">
                  New research conversation
                </p>
                <h2 className="font-heading text-3xl sm:text-4xl">
                  Ask the filing corpus
                </h2>
                <p className="mx-auto max-w-xl text-sm leading-6 text-muted-foreground">
                  Compare disclosures, trace changes over time, or inspect the evidence
                  behind a filing claim. Every factual answer is checked against its cited
                  source passage.
                </p>
              </div>
            ) : (
              <div className="space-y-8">
                {messages.map((message) => (
                  <ChatMessageView
                    key={message.id}
                    message={message}
                    onCitationSelect={(citation, trigger) => {
                      citationTriggerRef.current = trigger
                      setSelectedCitation(citation)
                    }}
                    selectedCitationId={selectedCitation?.citationId}
                  />
                ))}
                {isRunning ? (
                  <div
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                    aria-live="polite"
                  >
                    <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />
                    {turnStatus?.message ?? 'Starting research…'}
                  </div>
                ) : null}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="border-t bg-background px-5 py-4 sm:px-8 lg:px-12">
          <div className="mx-auto max-w-4xl space-y-3">
            <ChatComposer
              input={input}
              isRunning={isRunning}
              onInputChange={setInput}
              onStop={() => void stop()}
              onSubmit={handleSubmit}
            />
            {errorMessage ? (
              <div
                className="flex flex-wrap items-center justify-between gap-3 text-sm text-destructive"
                role="alert"
              >
                <span className="flex items-center gap-2">
                  <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
                  {errorMessage}
                </span>
                <div className="flex items-center gap-1">
                  {sessionExpired ? (
                    <Button
                      onClick={() => void signOut()}
                      size="xs"
                      type="button"
                      variant="outline"
                    >
                      Sign in again
                    </Button>
                  ) : null}
                  {retryable && failedUserId ? (
                    <Button onClick={handleRetry} size="xs" type="button" variant="outline">
                      <RotateCcw aria-hidden="true" />
                      Retry
                    </Button>
                  ) : null}
                  <Button
                    onClick={() => {
                      clearError()
                      setTurnFailure(null)
                    }}
                    size="xs"
                    type="button"
                    variant="ghost"
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            ) : null}
            <p className="text-center text-[0.68rem] leading-5 text-muted-foreground">
              Filing analysis only. Document Copilot does not provide investment advice.
            </p>
          </div>
        </div>
      </div>

      <CitationPanel citation={selectedCitation} onClose={closeCitation} />
    </section>
  )
}

function messageText(message: ChatMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
}

function isRetryableError(error: Error | undefined): boolean {
  if (!error) return false
  if (!(error instanceof ApiError)) return true
  return (
    error.isNetworkError ||
    error.status === 409 ||
    error.status === null ||
    error.status >= 500
  )
}
