import { ApiError } from '@/lib/http'

export function userFacingError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return 'Something went wrong. Please try again.'
  }
  if (error.isNetworkError) {
    return navigator.onLine
      ? 'Could not reach the API. It may be unavailable or blocked by CORS.'
      : 'You are offline. Reconnect and try again.'
  }
  if (error.status === 401) return 'Your session expired. Please sign in again.'
  if (error.status === 403) return 'You do not have access to this chat.'
  if (error.status === 404) return 'This chat no longer exists.'
  if (error.status === 409) {
    return 'Another message is already being sent to this chat.'
  }
  if (error.status === 422) {
    return 'Check the message or chat title and try again.'
  }
  if (error.status !== null && error.status >= 500) {
    return 'The server could not complete the request. Please try again.'
  }
  return error.message
}
