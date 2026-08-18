import { LogOut, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { ApiHealth } from '@/components/api-health'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth'

export function HomePage() {
  const { signOut, user } = useAuth()
  const [signOutError, setSignOutError] = useState<string | null>(null)

  async function handleSignOut() {
    setSignOutError(null)
    try {
      await signOut()
    } catch {
      setSignOutError('Could not sign out. Please try again.')
    }
  }

  return (
    <main className="min-h-svh bg-muted/40 px-6 py-10">
      <div className="mx-auto max-w-4xl space-y-8">
        <header className="flex items-center justify-between border-b pb-6">
          <div>
            <p className="font-heading text-2xl">10-K Club</p>
            <p className="text-xs tracking-[0.18em] text-muted-foreground uppercase">
              Document Copilot
            </p>
          </div>
          <Button variant="outline" onClick={() => void handleSignOut()}>
            <LogOut aria-hidden="true" />
            Sign out
          </Button>
        </header>

        <section className="border bg-background p-8 shadow-sm">
          <div className="flex items-start gap-4">
            <div className="grid size-10 shrink-0 place-items-center bg-primary text-primary-foreground">
              <ShieldCheck className="size-5" aria-hidden="true" />
            </div>
            <div className="space-y-2">
              <h1 className="font-heading text-3xl">Authentication is working</h1>
              <p className="text-sm text-muted-foreground">
                Signed in as {user?.email ?? 'your pilot account'}.
              </p>
              <ApiHealth />
            </div>
          </div>
          {signOutError ? (
            <p className="mt-5 text-sm text-destructive" role="alert">
              {signOutError}
            </p>
          ) : null}
        </section>
      </div>
    </main>
  )
}
