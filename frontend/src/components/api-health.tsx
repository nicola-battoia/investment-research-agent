import { CircleAlert, CircleCheck, LoaderCircle, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/http'

type HealthState =
  | { status: 'checking' }
  | { status: 'connected' }
  | { message: string; status: 'error' }

function errorState(error: unknown): HealthState {
  const message =
    error instanceof ApiError && error.isNetworkError
      ? 'FastAPI is not reachable'
      : 'FastAPI returned an error'
  return { message, status: 'error' }
}

export function ApiHealth() {
  const [health, setHealth] = useState<HealthState>({ status: 'checking' })

  const checkHealth = useCallback(async () => {
    setHealth({ status: 'checking' })
    try {
      const response = await api.getHealth()
      if (response.status !== 'ok') throw new Error('Unexpected health response')
      setHealth({ status: 'connected' })
    } catch (error) {
      setHealth(errorState(error))
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    void api
      .getHealth()
      .then((response) => {
        if (response.status !== 'ok') throw new Error('Unexpected health response')
        if (isMounted) setHealth({ status: 'connected' })
      })
      .catch((error: unknown) => {
        if (isMounted) setHealth(errorState(error))
      })
    return () => {
      isMounted = false
    }
  }, [])

  if (health.status === 'checking') {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />
        Checking FastAPI…
      </div>
    )
  }

  if (health.status === 'connected') {
    return (
      <div className="flex items-center gap-2 text-xs text-emerald-700">
        <CircleCheck className="size-3.5" aria-hidden="true" />
        FastAPI connected
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 text-xs text-destructive">
      <CircleAlert className="size-3.5" aria-hidden="true" />
      <span>{health.message}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        onClick={() => void checkHealth()}
        aria-label="Retry API health check"
      >
        <RefreshCw aria-hidden="true" />
      </Button>
    </div>
  )
}
