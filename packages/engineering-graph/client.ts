import { createClient, SupabaseClient } from "@supabase/supabase-js";

const env = (import.meta as any).env ?? {};
const url = env.VITE_SUPABASE_URL ?? "";
const key = env.VITE_SUPABASE_ANON_KEY ?? "";

if (!url || !key) {
  console.warn("[engineering-graph] VITE_SUPABASE_URL/ANON_KEY ausentes no .env");
}

// O fallback permite importar e testar o pacote fora do Vite. Nenhuma chamada
// de rede é feita até que um método do serviço seja executado.
export const graphClient: SupabaseClient = createClient(
  url || "http://127.0.0.1:54321",
  key || "engineering-graph-not-configured",
);
