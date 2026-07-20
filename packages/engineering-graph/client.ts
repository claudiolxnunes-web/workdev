import { createClient, SupabaseClient } from "@supabase/supabase-js";

const env = (import.meta as any).env ?? {};
const url = env.VITE_SUPABASE_URL ?? "";
const key = env.VITE_SUPABASE_ANON_KEY ?? "";

if (!url || !key) {
  console.warn("[engineering-graph] VITE_SUPABASE_URL/ANON_KEY ausentes no .env");
}

export const graphClient: SupabaseClient = createClient(url, key);
