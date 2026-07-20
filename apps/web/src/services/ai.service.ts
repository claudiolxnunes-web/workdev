const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface ProviderStatus {
  provider: string;
  label: string;
  connected: boolean;
}

export interface ProvidersStatusResponse {
  providers: ProviderStatus[];
  connected: number;
  total: number;
}

export async function getProvidersStatus(): Promise<ProvidersStatusResponse> {
  const response = await fetch("/api/ai/providers", { headers });
  if (!response.ok) throw new Error("Erro ao buscar status dos providers");
  return response.json();
}
