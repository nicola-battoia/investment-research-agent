import { DefaultChatTransport } from 'ai'

import { getAccessToken } from '@/lib/access-token'
import type { ChatMessage } from '@/lib/api'
import { env } from '@/lib/env'
import { ApiError, apiErrorFromResponse } from '@/lib/http'

async function authenticatedChatFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  try {
    const accessToken = await getAccessToken()
    if (!accessToken) {
      throw new ApiError('Your session has expired', { status: 401 })
    }

    const headers = new Headers(init?.headers)
    headers.set('Authorization', `Bearer ${accessToken}`)
    const response = await fetch(input, { ...init, headers })
    if (!response.ok) throw await apiErrorFromResponse(response)
    return response
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('Could not connect to the API', {
      cause: error,
      isNetworkError: true,
    })
  }
}

export function createChatTransport() {
  return new DefaultChatTransport<ChatMessage>({
    api: `${env.apiBaseUrl}/chat/stream`,
    fetch: authenticatedChatFetch,
    prepareSendMessagesRequest: ({ id, messages }) => {
      const message = messages.at(-1)
      if (!message) throw new Error('A chat message is required')
      return { body: { id, message } }
    },
  })
}
