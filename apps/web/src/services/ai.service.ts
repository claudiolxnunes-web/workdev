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

export async function updateProviderKey(provider: string, apiKey: string): Promise<void> {
  const response = await fetch(`/api/ai/providers/${provider}/key`, {
    method: "PUT",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) throw new Error("Erro ao salvar chave do provider");
}

export async function deleteProviderKey(provider: string): Promise<void> {
  const response = await fetch(`/api/ai/providers/${provider}/key`, {
    method: "DELETE",
    headers,
  });
  if (!response.ok) throw new Error("Erro ao remover chave do provider");
}

export async function sendAiChatWithConfirmation(
  payload: Record<string, unknown>,
  confirmFn: (message: string) => boolean = window.confirm,
) {
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })

  let data = await response.json()

  if (
    data.confirmation_required
    && confirmFn(`${data.reply}\n\nContinuar mesmo assim?`)
  ) {
    const retry = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...payload,
        user_confirmation: true,
      }),
    })

    data = await retry.json()
  }

  return data
}
