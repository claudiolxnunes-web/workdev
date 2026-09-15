const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface ExecutorSelection { provider: string; model: string; runtime_id?: string }
export interface ExecutionModel extends ExecutorSelection { agent: string; label: string; review_capable: boolean }

export async function getExecutionModels(): Promise<{ models: ExecutionModel[]; local_error: string | null }> {
  const response = await fetch("/api/settings/agent-models", { headers });
  if (!response.ok) throw new Error("Não foi possível carregar modelos para execução");
  const data = await response.json();
  if (!data || !Array.isArray(data.models)) throw new Error("Inventário de execução inválido");
  return data;
}

export interface AppSettings {
  agents?: { executor?: ExecutorSelection | null };
  app: {
    name: string;
    version: string;
    environment: string;
  };
  [key: string]: unknown;
}

export async function getSettings(): Promise<AppSettings> {
  const response = await fetch("/api/settings", { headers });
  if (!response.ok) throw new Error("Erro ao buscar configurações");
  return response.json();
}

export async function updateSettings(
  data: { app?: Partial<AppSettings["app"]> } & Partial<
    Omit<AppSettings, "app">
  >
): Promise<AppSettings> {
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Erro ao salvar configurações");
  return response.json();
}
