const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface ChatLivreConversation {
  id: string;
  title: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface ChatLivreMessage {
  id: string;
  role: string;
  content: string;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  created_at: string;
}

export interface ChatLivreConversationDetail extends ChatLivreConversation {
  messages: ChatLivreMessage[];
}

export async function listConversations(q?: string): Promise<ChatLivreConversation[]> {
  const url = q && q.trim()
    ? `/api/chat-livre/conversations?q=${encodeURIComponent(q.trim())}`
    : "/api/chat-livre/conversations";
  const r = await fetch(url, { headers });
  if (!r.ok) throw new Error("Erro ao listar conversas");
  return r.json();
}

export async function createConversation(title?: string): Promise<ChatLivreConversation> {
  const r = await fetch("/api/chat-livre/conversations", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  });
  if (!r.ok) throw new Error("Erro ao criar conversa");
  return r.json();
}

export async function getConversation(id: string): Promise<ChatLivreConversationDetail> {
  const r = await fetch(`/api/chat-livre/conversations/${id}`, { headers });
  if (!r.ok) throw new Error("Erro ao abrir conversa");
  return r.json();
}

export async function renameConversation(id: string, title: string): Promise<ChatLivreConversation> {
  const r = await fetch(`/api/chat-livre/conversations/${id}`, {
    method: "PATCH",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("Erro ao renomear conversa");
  return r.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`/api/chat-livre/conversations/${id}`, {
    method: "DELETE",
    headers,
  });
  if (!r.ok) throw new Error("Erro ao apagar conversa");
}

export interface SendMessagePayload {
  content: string;
  provider: string;
  model?: string | null;
  runtime_id?: string | null;
}

export interface StreamDone {
  message: ChatLivreMessage;
  conversation_tokens: number;
  context_limit: number | null;
  context_warning: boolean;
  truncated: boolean;
  cost_usd: number | null;
}

export interface StreamCallbacks {
  onDelta: (text: string) => void;
  onDone: (done: StreamDone) => void;
  onError: (message: string) => void;
}

/** Envia a mensagem e consome o SSE. O backend nunca envia tools ao modelo. */
export async function sendMessage(
  conversationId: string,
  payload: SendMessagePayload,
  cb: StreamCallbacks,
): Promise<void> {
  const r = await fetch(`/api/chat-livre/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok || !r.body) {
    cb.onError(`Erro HTTP ${r.status} ao enviar mensagem`);
    return;
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  const handleData = (data: string) => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(data);
    } catch {
      return;
    }
    if (currentEvent === "delta") {
      cb.onDelta(String(parsed.content ?? ""));
    } else if (currentEvent === "done") {
      cb.onDone(parsed as unknown as StreamDone);
    } else if (currentEvent === "error") {
      cb.onError(String(parsed.message ?? "Erro no chat"));
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        handleData(line.slice(5).trim());
      }
    }
  }
}
