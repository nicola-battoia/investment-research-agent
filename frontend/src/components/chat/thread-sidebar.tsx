import {
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import type { ChatThread } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ThreadSidebarProps {
  isCreating: boolean
  onCreate: () => Promise<void>
  onDelete: (threadId: string) => Promise<void>
  onRename: (threadId: string, title: string) => Promise<void>
  onSelect: (threadId: string) => void
  onSignOut: () => Promise<void>
  selectedThreadId?: string
  threads: ChatThread[]
  userEmail?: string
}

export function ThreadSidebar({
  isCreating,
  onCreate,
  onDelete,
  onRename,
  onSelect,
  onSignOut,
  selectedThreadId,
  threads,
  userEmail,
}: ThreadSidebarProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ChatThread | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  async function submitRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!renamingId || !renameValue.trim()) return
    try {
      await onRename(renamingId, renameValue)
      setRenamingId(null)
    } catch {
      // The page-level alert owns the user-facing error.
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      await onDelete(deleteTarget.id)
      setDeleteTarget(null)
      setMobileOpen(false)
    } catch {
      // Keep the dialog open while the page-level alert explains the failure.
    } finally {
      setIsDeleting(false)
    }
  }

  function selectThread(id: string) {
    setMobileOpen(false)
    onSelect(id)
  }

  function createChat() {
    setMobileOpen(false)
    void onCreate()
  }

  const sidebarBody = (
    <div className="flex h-full min-h-0 flex-col bg-muted/30">
      <header className="flex items-center justify-between border-b px-5 py-5">
        <Brand />
        <Button
          aria-label="Create new chat"
          disabled={isCreating}
          onClick={createChat}
          size="icon-sm"
        >
          <Plus aria-hidden="true" />
        </Button>
      </header>

      <nav className="min-h-0 flex-1 overflow-y-auto p-3" aria-label="Chat threads">
        {threads.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs leading-5 text-muted-foreground">
            No chats yet. Create one to start a conversation.
          </p>
        ) : (
          <ul className="space-y-1">
            {threads.map((thread) => (
              <li key={thread.id}>
                {renamingId === thread.id ? (
                  <form className="flex items-center gap-2 p-1" onSubmit={submitRename}>
                    <Input
                      aria-label="Chat title"
                      autoFocus
                      maxLength={200}
                      onChange={(event) => setRenameValue(event.currentTarget.value)}
                      value={renameValue}
                    />
                    <Button size="xs" type="submit" disabled={!renameValue.trim()}>
                      Save
                    </Button>
                    <Button
                      size="xs"
                      type="button"
                      variant="ghost"
                      onClick={() => setRenamingId(null)}
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <div
                    className={cn(
                      'group flex items-center border-l-2 border-transparent',
                      selectedThreadId === thread.id && 'border-primary bg-background',
                    )}
                  >
                    <button
                      className="flex min-w-0 flex-1 items-center gap-2 px-3 py-3 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                      onClick={() => selectThread(thread.id)}
                      type="button"
                    >
                      <MessageSquare
                        className="size-3.5 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                      <span className="truncate">{thread.title}</span>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            aria-label={`Actions for ${thread.title}`}
                            className="mr-1 opacity-70 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100"
                            size="icon-xs"
                            variant="ghost"
                          />
                        }
                      >
                        <MoreHorizontal aria-hidden="true" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => {
                            setRenamingId(thread.id)
                            setRenameValue(thread.title)
                          }}
                        >
                          <Pencil aria-hidden="true" />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          onClick={() => setDeleteTarget(thread)}
                        >
                          <Trash2 aria-hidden="true" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </nav>

      <footer className="flex items-center justify-between gap-3 border-t px-4 py-3">
        <span className="min-w-0 truncate text-xs text-muted-foreground">
          {userEmail ?? 'Pilot account'}
        </span>
        <Button
          aria-label="Sign out"
          onClick={() => void onSignOut()}
          size="icon-xs"
          variant="ghost"
        >
          <LogOut aria-hidden="true" />
        </Button>
      </footer>
    </div>
  )

  return (
    <>
      <header className="flex items-center justify-between border-b bg-muted/30 px-4 py-3 md:hidden">
        <Button
          aria-label="Open chat list"
          onClick={() => setMobileOpen(true)}
          size="icon-sm"
          variant="ghost"
        >
          <Menu aria-hidden="true" />
        </Button>
        <Brand compact />
        <Button
          aria-label="Create new chat"
          disabled={isCreating}
          onClick={createChat}
          size="icon-sm"
        >
          <Plus aria-hidden="true" />
        </Button>
      </header>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent className="w-[min(90vw,22rem)] p-0" side="left">
          <SheetHeader className="sr-only">
            <SheetTitle>Chat threads</SheetTitle>
            <SheetDescription>Select or manage a research conversation.</SheetDescription>
          </SheetHeader>
          {sidebarBody}
        </SheetContent>
      </Sheet>

      <aside className="hidden w-80 shrink-0 border-r md:block">{sidebarBody}</aside>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete chat?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleteTarget?.title}” and its message history will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={isDeleting}
              variant="destructive"
              onClick={() => void confirmDelete()}
            >
              {isDeleting ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? 'text-center' : undefined}>
      <p className={cn('font-heading', compact ? 'text-base' : 'text-xl')}>10-K Club</p>
      <p className="text-[0.6rem] tracking-[0.18em] text-muted-foreground uppercase">
        Document Copilot
      </p>
    </div>
  )
}
