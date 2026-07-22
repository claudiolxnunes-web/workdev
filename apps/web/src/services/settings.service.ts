const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface AppSettings {
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
