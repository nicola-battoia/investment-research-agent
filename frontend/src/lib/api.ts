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

export type AnswerStatus =
  | 'conversational'
  | 'out_of_scope'
  | 'supported'
  | 'insufficient_evidence'
  | 'investment_advice_refused'

export interface CitationTextHighlight {
  end: number
  start: number
}

export interface TextCitationPassage {
  highlights: CitationTextHighlight[]
  kind: 'text'
  text: string
  version: 1
}

export interface CitationTableCell {
  columnHeader: boolean
  columnIndex: number
  columnSpan: number
  highlighted: boolean
  rowHeader: boolean
  rowSpan: number
  text: string
}

export interface CitationTableRow {
  cells: CitationTableCell[]
}

export interface TableCitationPassage {
  columnCount: number
  kind: 'table'
  rows: CitationTableRow[]
  version: 1
}

export type CitationPassage = TextCitationPassage | TableCitationPassage

export interface CitationData {
  accessionNumber: string
  chunkId: string
  chunkIndex: number
  citationId: string
  citationIndex: number
  company: string
  documentId: string
  excerpt: string
  filingDate: string
  filingType: string
  pageNumber: number | null
  passage: CitationPassage | null
  reportDate: string
  secUrl: string
  sectionTitle: string | null
  sourceEnd: number | null
  sourceId: string
  sourceStart: number | null
  ticker: string
}

export interface TurnStatusData {
  message: string
  state: 'researching'
}

export interface TurnErrorData {
  code: string
  message: string
  retryable: boolean
}

export type ChatDataParts = {
  citation: CitationData
  'turn-error': TurnErrorData
  'turn-status': TurnStatusData
}

export interface ChatMessageMetadata {
  answerStatus?: AnswerStatus | null
  createdAt: string
}

export type ChatMessage = UIMessage<ChatMessageMetadata, ChatDataParts>

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
