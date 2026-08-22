import { CircleAlert, LoaderCircle, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ChatConversation } from '@/components/chat/chat-conversation'
import { ThreadSidebar } from '@/components/chat/thread-sidebar'
import { Button } from '@/components/ui/button'
import { api, type ChatThread, type ChatThreadDetail } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ApiError } from '@/lib/http'
import { userFacingError } from '@/lib/user-facing-error'

export function ChatPage() {
  const { threadId } = useParams<{ threadId: string }>()
  const navigate = useNavigate()
  const { signOut, user } = useAuth()
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [threadDetail, setThreadDetail] = useState<ChatThreadDetail | null>(null)
  const [isLoadingThreads, setIsLoadingThreads] = useState(true)
  const [resolvedThreadId, setResolvedThreadId] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const loadThreads = useCallback(async () => {
    const loadedThreads = await api.listThreads()
    setThreads(loadedThreads)
    return loadedThreads
  }, [])

  useEffect(() => {
    let active = true
    void api
      .listThreads()
      .then((loadedThreads) => {
        if (!active) return
        setThreads(loadedThreads)
        setError(null)
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError)
      })
      .finally(() => {
        if (active) setIsLoadingThreads(false)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!threadId && !isLoadingThreads && threads.length > 0) {
      navigate(`/chat/${threads[0].id}`, { replace: true })
    }
  }, [isLoadingThreads, navigate, threadId, threads])

  useEffect(() => {
    let active = true
    if (!threadId) {
      return () => {
        active = false
      }
    }

    void api
      .getThread(threadId)
      .then((detail) => {
        if (!active) return
        setThreadDetail(detail)
        setError(null)
      })
      .catch((loadError: unknown) => {
        if (active) setError(loadError)
      })
      .finally(() => {
        if (active) setResolvedThreadId(threadId)
      })
    return () => {
      active = false
    }
  }, [threadId])

  async function handleCreate() {
    setIsCreating(true)
    setError(null)
    try {
      const thread = await api.createThread()
      setThreads((current) => [thread, ...current])
      navigate(`/chat/${thread.id}`)
    } catch (createError) {
      setError(createError)
    } finally {
      setIsCreating(false)
    }
  }

  async function handleRename(id: string, title: string) {
    setError(null)
    try {
      const renamed = await api.renameThread(id, title)
      setThreads((current) =>
        current.map((thread) => (thread.id === id ? renamed : thread)),
      )
      setThreadDetail((current) =>
        current?.thread.id === id ? { ...current, thread: renamed } : current,
      )
    } catch (renameError) {
      setError(renameError)
      throw renameError
    }
  }

  async function handleDelete(id: string) {
    setError(null)
    try {
      await api.deleteThread(id)
      const remaining = threads.filter((thread) => thread.id !== id)
      setThreads(remaining)
      if (threadId === id) {
        navigate(remaining[0] ? `/chat/${remaining[0].id}` : '/', { replace: true })
      }
    } catch (deleteError) {
      setError(deleteError)
      throw deleteError
    }
  }

  async function handleSignOut() {
    setError(null)
    try {
      await signOut()
    } catch (signOutError) {
      setError(signOutError)
    }
  }

  function handleTurnFinished() {
    void Promise.all([
      loadThreads(),
      threadId ? api.getThread(threadId) : Promise.resolve(null),
    ])
      .then(([, detail]) => {
        if (detail) setThreadDetail(detail)
      })
      .catch((loadError: unknown) => setError(loadError))
  }

  const showSignInAction = error instanceof ApiError && error.status === 401
  const isLoadingThread = Boolean(threadId && resolvedThreadId !== threadId)

  return (
    <main className="flex min-h-svh flex-col bg-background md:flex-row">
      <ThreadSidebar
        isCreating={isCreating}
        onCreate={handleCreate}
        onDelete={handleDelete}
        onRename={handleRename}
        onSelect={(id) => navigate(`/chat/${id}`)}
        onSignOut={handleSignOut}
        selectedThreadId={threadId}
        threads={threads}
        userEmail={user?.email}
      />

      <div className="flex min-h-0 flex-1 flex-col">
        {error ? (
          <div className="flex items-center justify-between gap-4 border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-sm text-destructive" role="alert">
            <span className="flex items-center gap-2">
              <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
              {userFacingError(error)}
            </span>
            {showSignInAction ? (
              <Button size="xs" variant="outline" onClick={() => void handleSignOut()}>
                Sign in again
              </Button>
            ) : (
              <Button size="xs" variant="ghost" onClick={() => setError(null)}>
                Dismiss
              </Button>
            )}
          </div>
        ) : null}

        {isLoadingThreads || isLoadingThread ? (
          <div className="grid flex-1 place-items-center">
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              Loading chat…
            </p>
          </div>
        ) : threadId && threadDetail?.thread.id === threadId ? (
          <>
            <header className="border-b px-5 py-4 sm:px-8">
              <h1 className="truncate font-heading text-xl">{threadDetail.thread.title}</h1>
            </header>
            <ChatConversation
              key={threadDetail.thread.id}
              initialMessages={threadDetail.messages}
              onTurnFinished={handleTurnFinished}
              threadId={threadDetail.thread.id}
            />
          </>
        ) : (
          <div className="grid flex-1 place-items-center px-6 py-16 text-center">
            <div className="max-w-md space-y-5">
              <p className="text-xs font-semibold tracking-[0.2em] text-muted-foreground uppercase">
                Secure analyst workspace
              </p>
              <h1 className="font-heading text-4xl">Start a new research chat</h1>
              <p className="text-sm leading-6 text-muted-foreground">
                Chats are private to your account and restored whenever you return.
              </p>
              <Button onClick={() => void handleCreate()} disabled={isCreating}>
                <Plus aria-hidden="true" />
                {isCreating ? 'Creating…' : 'New chat'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
