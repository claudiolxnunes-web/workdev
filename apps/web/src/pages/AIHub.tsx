import { useState, useRef, useEffect } from "react";
import { Trash2 } from "lucide-react";
import { MessageBubble, PlanningPanel, type Msg } from "@/components/ai-hub";

interface SessionMeta {
  id: string;
  title: string;
  updated_at: string;
}

const MODELOS = [
  { label: "GPT-4o", provider: "openai", model: "gpt-4o" },
  { label: "GPT-4o mini", provider: "openai", model: "gpt-4o-mini" },
  { label: "Claude Sonnet 4.6", provider: "anthropic", model: "claude-sonnet-4-6" },
  { label: "Claude Haiku 4.5", provider: "anthropic", model: "claude-haiku-4-5-20251001" },
  { label: "GPT-OSS 20B (Ollama Cloud)", provider: "ollama", model: "gpt-oss:20b" },
  { label: "Kimi K2.6", provider: "kimi", model: "kimi-k2.6" },
  { label: "Kimi K2.7 Code", provider: "kimi", model: "kimi-k2.7-code" },
  { label: "Kimi K3 (OpenRouter)", provider: "openrouter", model: "moonshotai/kimi-k3" },
  { label: "Gemini 3.5 Flash", provider: "gemini", model: "gemini-3.5-flash" },
  { label: "Nemotron Ultra 550B (free)", provider: "openrouter", model: "nvidia/nemotron-3-ultra-550b-a55b:free" },
  { label: "Qwen3 Coder", provider: "openrouter", model: "qwen/qwen3-coder" },
];
const MODELO_STORAGE_KEY = "workdev_ai_hub_modelo";
const DEFAULT_MODELO_LABEL = "GPT-4o";

function loadStoredModelo() {
  try {
    const stored = localStorage.getItem(MODELO_STORAGE_KEY);
    const found = stored && MODELOS.find((m) => m.label === stored);
    if (found) return found;
  } catch { /* localStorage indisponível (modo privado etc.) */ }
  return MODELOS.find((m) => m.label === DEFAULT_MODELO_LABEL) || MODELOS[0];
}

export default function AIHub() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(
    () => sessionStorage.getItem("workdev_chat_session")
  );
  const [input, setInput] = useState("");
  const [modelo, setModelo] = useState(loadStoredModelo);
  const [loading, setLoading] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showPlans, setShowPlans] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const panel = messagesRef.current;
    if (panel) panel.scrollTop = panel.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    // Intencional: roda só no mount, lendo o sessionId inicial (sessionStorage).
    // Incluir sessionId/restoreSession nas deps re-rodaria a cada troca de
    // sessão (restoreSession chama setSessionId), criando um loop.
    loadSessions();
    if (sessionId) restoreSession(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadSessions() {
    try {
      const r = await fetch("/api/chat/sessions");
      if (r.ok) setSessions(await r.json());
    } catch { /* silencioso */ }
  }

  async function restoreSession(id: string) {
    try {
      const r = await fetch(`/api/chat/sessions/${id}`);
      if (!r.ok) { newChat(); return; }
      const data = await r.json();
      setMessages(data.messages);
      setSessionId(id);
      sessionStorage.setItem("workdev_chat_session", id);
    } catch { /* silencioso */ }
  }

  function newChat() {
    setMessages([]);
    setSessionId(null);
    sessionStorage.removeItem("workdev_chat_session");
  }

  async function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Apagar esta conversa?")) return;
    try {
      await fetch(`/api/chat/sessions/${id}`, { method: "DELETE" });
      if (id === sessionId) newChat();
      loadSessions();
    } catch { /* silencioso */ }
  }

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    const next: Msg[] = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const r = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next, session_id: sessionId, provider: modelo.provider, model: modelo.model }),
      });
      const data = await r.json();
      setMessages([
        ...next,
        { role: "assistant" as const, content: data.reply || "Erro na resposta", error: !!data.error },
      ]);
      if (data.session_id) {
        setSessionId(data.session_id);
        sessionStorage.setItem("workdev_chat_session", data.session_id);
        loadSessions();
      }
    } catch {
      setMessages([
        ...next,
        { role: "assistant" as const, content: "Erro ao falar com a API", error: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-[calc(100dvh-9rem)] min-h-[520px] min-w-0 max-w-full gap-3 overflow-hidden lg:gap-4">
      {showSidebar && (
        <div className="hidden w-56 shrink-0 flex-col rounded-xl border border-slate-800 bg-slate-900 p-3 md:flex xl:w-64">
          <button
            onClick={newChat}
            className="bg-blue-600 hover:bg-blue-700 rounded-lg px-3 py-2 text-sm mb-3 transition-colors"
          >
            + Nova conversa
          </button>
          <div className="flex-1 overflow-y-auto space-y-1">
            {sessions.length === 0 && (
              <p className="text-slate-600 text-xs px-1">Nenhuma conversa salva</p>
            )}
            {sessions.map((s) => (
              <div
                key={s.id}
                onClick={() => restoreSession(s.id)}
                className={`group flex items-center gap-2 rounded-lg px-3 py-2 text-xs cursor-pointer transition-colors ${
                  s.id === sessionId
                    ? "bg-slate-700 text-white"
                    : "text-slate-400 hover:bg-slate-800"
                }`}
              >
                <span className="flex-1 truncate" title={s.title}>{s.title}</span>
                <button
                  onClick={(e) => deleteSession(s.id, e)}
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity"
                  title="Apagar conversa"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="mb-3 flex min-w-0 items-center gap-3">
          <button
            onClick={() => setShowSidebar(!showSidebar)}
            className="text-slate-400 hover:text-white text-xl"
            title="Alternar histórico"
          >
            ☰
          </button>
          <h1 className="truncate text-2xl font-bold sm:text-3xl">AI Hub</h1>
          <button
            onClick={() => setShowPlans(true)}
            className="ml-auto rounded-lg border border-violet-700 bg-violet-950/60 px-3 py-2 text-sm text-violet-200 hover:bg-violet-900"
          >
            Planos
          </button>
        </div>
        <div ref={messagesRef} className="min-h-0 min-w-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto overscroll-contain rounded-xl border border-slate-800 bg-slate-900 p-3 sm:p-4">
          {messages.length === 0 && (
            <p className="text-slate-500 text-sm">
              Converse com o WorkDev. Ex: "quantos itens high estão pendentes?",
              "cria uma task no nutrigestor: ajustar favicon", "status dos projetos"
            </p>
          )}
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {loading && (
            <div className="max-w-[75%] rounded-2xl rounded-bl-sm bg-slate-800 px-4 py-2.5 text-sm text-slate-400">
              Pensando...
            </div>
          )}
          <div ref={endRef} />
        </div>
        <div className="mt-3 flex min-w-0 flex-wrap gap-2 sm:flex-nowrap sm:gap-3">
          <input
            className="min-w-0 flex-[1_1_100%] rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 text-sm sm:flex-1"
            placeholder="Pergunte ou peça algo ao WorkDev..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <select
            value={modelo.label}
            onChange={(e) => {
              const next = MODELOS.find((m) => m.label === e.target.value) || MODELOS[0];
              setModelo(next);
              try { localStorage.setItem(MODELO_STORAGE_KEY, next.label); } catch { /* ignore */ }
            }}
            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-3 text-sm text-slate-300 sm:max-w-64"
          >
            {MODELOS.map((m) => (
              <option key={m.label} value={m.label}>{m.label}</option>
            ))}
          </select>
          <button
            onClick={send}
            disabled={loading}
            className="shrink-0 rounded-lg bg-blue-600 px-5 py-3 transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            Enviar
          </button>
        </div>
      </div>
      {showPlans && <PlanningPanel onClose={() => setShowPlans(false)} />}
    </div>
  );
}
