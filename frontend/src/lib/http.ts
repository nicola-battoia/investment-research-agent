export interface ApiErrorOptions {
  cause?: unknown
  isNetworkError?: boolean
  status?: number
}

export class ApiError extends Error {
  readonly isNetworkError: boolean
  readonly status: number | null

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message, { cause: options.cause })
    this.name = 'ApiError'
    this.isNetworkError = options.isNetworkError ?? false
    this.status = options.status ?? null
  }
}

type AccessTokenProvider = () => Promise<string | null>

interface RequestOptions {
  body?: unknown
  method: 'DELETE' | 'GET' | 'PATCH' | 'POST' | 'PUT'
  timeoutMs?: number
}

function errorMessage(payload: unknown, fallback: string): string {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload &&
    typeof payload.detail === 'string'
  ) {
    return payload.detail
  }
  return fallback
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null

  try {
    return JSON.parse(text)
  } catch (error) {
    throw new ApiError('The API returned invalid JSON', {
      cause: error,
      status: response.status,
    })
  }
}

export function createHttpClient(
  baseUrl: string,
  getAccessToken: AccessTokenProvider,
) {
  const normalizedBaseUrl = baseUrl.replace(/\/+$/, '')

  async function request<T>(
    path: string,
    { body, method, timeoutMs = 10_000 }: RequestOptions,
  ): Promise<T> {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)

    try {
      const accessToken = await getAccessToken()
      const headers = new Headers({ Accept: 'application/json' })
      if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
      if (body !== undefined) headers.set('Content-Type', 'application/json')

      const response = await fetch(
        `${normalizedBaseUrl}${path.startsWith('/') ? path : `/${path}`}`,
        {
          body: body === undefined ? undefined : JSON.stringify(body),
          headers,
          method,
          signal: controller.signal,
        },
      )
      const payload = await readJson(response)

      if (!response.ok) {
        throw new ApiError(
          errorMessage(payload, `API request failed with status ${response.status}`),
          { status: response.status },
        )
      }

      return payload as T
    } catch (error) {
      if (error instanceof ApiError) throw error
      const timedOut = error instanceof DOMException && error.name === 'AbortError'
      throw new ApiError(
        timedOut ? 'The API request timed out' : 'Could not connect to the API',
        { cause: error, isNetworkError: true },
      )
    } finally {
      window.clearTimeout(timeout)
    }
  }

  return {
    delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
    get: <T>(path: string) => request<T>(path, { method: 'GET' }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { body, method: 'PATCH' }),
    post: <T>(path: string, body: unknown) =>
      request<T>(path, { body, method: 'POST' }),
    put: <T>(path: string, body: unknown) =>
      request<T>(path, { body, method: 'PUT' }),
  }
}
