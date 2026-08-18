import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'

import { ApiHealth } from '@/components/api-health'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/lib/auth'

export function SignInPage() {
  const { isLoading, session, signIn } = useAuth()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isLoading && session) return <Navigate to="/" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setErrorMessage(null)
    setIsSubmitting(true)

    const form = new FormData(event.currentTarget)
    const email = String(form.get('email') ?? '').trim()
    const password = String(form.get('password') ?? '')

    try {
      await signIn(email, password)
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : 'Unable to sign in right now',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-svh bg-muted/40 lg:grid-cols-[1fr_30rem]">
      <section className="hidden border-r bg-primary p-12 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
        <p className="font-heading text-2xl">10-K Club</p>
        <div className="max-w-xl space-y-5">
          <p className="text-xs font-semibold tracking-[0.22em] uppercase opacity-70">
            Document Copilot
          </p>
          <h1 className="font-heading text-5xl leading-tight">
            Filing research, with every answer tied to its source.
          </h1>
          <p className="max-w-lg text-sm leading-6 opacity-75">
            This pilot is private. Sign in with the account created for you by
            the project administrator.
          </p>
        </div>
        <ApiHealth />
      </section>

      <section className="flex items-center px-6 py-12 sm:px-10">
        <div className="mx-auto w-full max-w-sm space-y-8">
          <div className="space-y-2">
            <p className="font-heading text-2xl lg:hidden">10-K Club</p>
            <h2 className="font-heading text-4xl text-foreground">Sign in</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              New account creation is disabled for this private pilot.
            </p>
          </div>

          <form className="space-y-5" onSubmit={(event) => void handleSubmit(event)}>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="analyst@company.com"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>

            {errorMessage ? (
              <p className="text-sm text-destructive" role="alert">
                {errorMessage}
              </p>
            ) : null}

            <Button className="w-full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <div className="lg:hidden">
            <ApiHealth />
          </div>
        </div>
      </section>
    </main>
  )
}
