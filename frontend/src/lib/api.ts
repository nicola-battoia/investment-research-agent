import type { UIMessage } from 'ai'

import { getAccessToken } from '@/lib/access-token'
import { env } from '@/lib/env'
import { createHttpClient } from '@/lib/http'

const http = createHttpClient(env.apiBaseUrl, getAccessToken)

export interface HealthResponse {
  status: 'ok'
}

export interface ChatThread {
  createdAt: string
  id: string
  title: string
  updatedAt: string
}

export interface MessageCitation {
  chunkId: string
  citationIndex: number
  excerpt: string
  id: string
}

export interface ChatMessageMetadata {
  citations: MessageCitation[]
  createdAt: string
}

export type ChatMessage = UIMessage<ChatMessageMetadata>

export interface ChatThreadDetail {
  messages: ChatMessage[]
  thread: ChatThread
}

export const api = {
  createThread: (title?: string) =>
    http.post<ChatThread>('/chat/threads', title ? { title } : {}),
  deleteThread: (threadId: string) =>
    http.delete<void>(`/chat/threads/${threadId}`),
  getHealth: () => http.get<HealthResponse>('/health'),
  getThread: (threadId: string) =>
    http.get<ChatThreadDetail>(`/chat/threads/${threadId}`),
  listThreads: () => http.get<ChatThread[]>('/chat/threads'),
  renameThread: (threadId: string, title: string) =>
    http.patch<ChatThread>(`/chat/threads/${threadId}`, { title }),
}
