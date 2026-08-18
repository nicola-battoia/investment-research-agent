import { env } from '@/lib/env'
import { createHttpClient } from '@/lib/http'
import { supabase } from '@/lib/supabase'

const http = createHttpClient(env.apiBaseUrl, async () => {
  const { data, error } = await supabase.auth.getSession()
  if (error) throw error
  return data.session?.access_token ?? null
})

export interface HealthResponse {
  status: 'ok'
}

export const api = {
  getHealth: () => http.get<HealthResponse>('/health'),
}
