type RequiredEnvName =
  | 'VITE_API_BASE_URL'
  | 'VITE_SUPABASE_URL'
  | 'VITE_SUPABASE_ANON_KEY'

function readRequired(name: RequiredEnvName): string {
  const value: unknown = import.meta.env[name]

  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Missing required environment variable: ${name}`)
  }

  return value.trim()
}

function readHttpUrl(name: RequiredEnvName): string {
  const value = readRequired(name)

  try {
    const url = new URL(value)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error()
    }
    return url.toString().replace(/\/$/, '')
  } catch {
    throw new Error(`${name} must be a valid HTTP or HTTPS URL`)
  }
}

export const env = Object.freeze({
  apiBaseUrl: readHttpUrl('VITE_API_BASE_URL'),
  supabaseUrl: readHttpUrl('VITE_SUPABASE_URL'),
  supabaseAnonKey: readRequired('VITE_SUPABASE_ANON_KEY'),
})
