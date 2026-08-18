import { createClient } from '@supabase/supabase-js'

import { env } from '@/lib/env'

export const supabase = createClient(env.supabaseUrl, env.supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    detectSessionInUrl: true,
    persistSession: true,
  },
})
