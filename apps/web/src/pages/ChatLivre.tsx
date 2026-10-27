import { useState, useRef, useEffect, useCallback, startTransition } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Trash2, Pencil, Check, X, AlertTriangle } from "lucide-react";
import {
  listConversations,
  createConversation,
  getConversation,
  renameConversation,
  deleteConversation,
  sendMessage,
  type ChatLivreConversation,
  type ChatLivreMessage,
} from "../services/chatLivre.service";
import { getOpenRouterModels, getLocalModels, type CatalogModel } from "../services/ai.service";
import { MessageBubble, type Msg } from "@/components/ai-hub";

// Provedores OpenAI-compatíveis que funcionam no chat livre. Claude
// (Anthropic) fica de fora: usa API própria, não o protocolo OpenAI que o
// chat livre fala — oferecê-lo daria erro 422. Kimi vai pelo OpenRouter
// (moonshotai/kimi-*) porque o provider Kimi direto está sem cota (429);
// Gemini idem, entra de volta quando a conta tiver crédito.
const MODELOS = [
  { label: "GPT-4o mini", provider: "openai", model: "gpt-4o-mini" },
  { label: "OpenRouter (Kimi e outros)", provider: "openrouter", model: null },
  { label: "Local / Ollama", provider: "ollama", model: null },
];
const modelKey = (m: CatalogModel) => (m.runtime_id ? JSON.stringify([m.runtime_id, m.model]) : m.model);

interface LiveMsg extends Msg {
  model?: string | null;
}

export default function ChatLivre() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();

  const [conversations, setConversations] = useState<ChatLivreConversation[]>([]);
  const [active, setActive] = useState<ChatLivreConversation | null>(null);
  const [messages, setMessages] = useState<LiveMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [search, setSearch] = useState("");
  const [tokens, setTokens] = useState(0);
  const [contextLimit, setContextLimit] = useState<number | null>(null);
  const [contextWarning, setContextWarning] = useState(false);
  const [cost, setCost] = useState(0);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  const [modelo, setModelo] = useState(MODELOS[0]);
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([]);
  const [catalogModel, setCatalogModel] = useState("");
  const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "error">("loading");

  const dynamicSource = modelo.provider === "openrouter" || modelo.provider === "ollama";
  const localSource = modelo.provider === "ollama";
  const selectedEntry = dynamicSource && catalogStatus === "ready"
    ? catalogModels.find((m) => modelKey(m) === catalogModel) : undefined;
  const selectedModel = dynamicSource ? selectedEntry?.model : modelo.model;

  const messagesRef = useRef<HTMLDivElement>(null);

  const loadList = useCallback(async (q?: string) => {
    try {
      setConversations(await listConversations(q));
    } catch { /* silencioso */ }
  }, []);

  useEffect(() => {
    startTransition(() => {
      loadList();
    });
  }, [loadList]);

  useEffect(() => {
    if (!dynamicSource) return;
    let active = true;
    startTransition(() => setCatalogStatus("loading"));
    (localSource ? getLocalModels() : getOpenRouterModels()).then((models) => {
      if (!active) return;
      setCatalogModels(models);
      setCatalogModel((cur) => (models.some((m) => modelKey(m) === cur) ? cur : ""));
      setCatalogStatus("ready");
    }).catch(() => {
      if (active) { setCatalogModels([]); setCatalogStatus("error"); }
    });
    return () => { active = false; };
  }, [modelo.provider, dynamicSource, localSource]);

  useEffect(() => {
    if (!conversationId) {
      startTransition(() => {
        setActive(null);
        setMessages([]);
        setTokens(0);
        setCost(0);
        setContextWarning(false);
      });
      return;
    }
    let cancelled = false;
    getConversation(conversationId).then((data) => {
      if (cancelled) return;
      setActive(data);
      setMessages(data.messages.map((m: ChatLivreMessage) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
        model: m.model,
      })));
      setTokens(data.input_tokens || 0);
      setCost(data.cost_usd || 0);
      setContextWarning(false);
    }).catch(() => {
      if (!cancelled) navigate("/chat-livre", { replace: true });
    });
    return () => { cancelled = true; };
  }, [conversationId, navigate]);

  useEffect(() => {
    const panel = messagesRef.current;
    if (panel) panel.scrollTop = panel.scrollHeight;
  }, [messages, streaming, loading]);

  async function novaConversa() {
    try {
      const conv = await createConversation();
      await loadList();
      navigate(`/chat-livre/${conv.id}`);
    } catch { /* silencioso */ }
  }

  async function apagar(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Apagar esta conversa?")) return;
    try {
      await deleteConversation(id);
      await loadList(search);
      if (id === conversationId) navigate("/chat-livre");
    } catch { /* silencioso */ }
  }

  async function confirmarRenomear() {
    const title = renameValue.trim();
    if (!active || !title) { setRenaming(false); return; }
    try {
      const updated = await renameConversation(active.id, title);
      setActive(updated);
      await loadList(search);
    } catch { /* silencioso */ }
    setRenaming(false);
  }

  async function enviar() {
    const text = input.trim();
    if (!text || loading || !selectedModel) return;

    let convId = conversationId;
    if (!convId) {
      try {
        const conv = await createConversation();
        convId = conv.id;
        navigate(`/chat-livre/${conv.id}`, { replace: true });
      } catch {
        return;
      }
    }

    const next: LiveMsg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    setStreaming("");

    let acc = "";
    await sendMessage(convId, {
      content: text,
      provider: modelo.provider,
      model: selectedModel,
      ...(localSource ? { runtime_id: selectedEntry?.runtime_id } : {}),
    }, {
      onDelta: (d) => { acc += d; setStreaming(acc); },
      onDone: (done) => {
        setMessages([...next, {
          role: "assistant",
          content: done.message.content,
          model: done.message.model,
        }]);
        setStreaming("");
        setTokens(done.conversation_tokens);
        setContextLimit(done.context_limit);
        setContextWarning(done.context_warning);
        if (done.cost_usd != null) setCost((c) => c + done.cost_usd!);
        loadList(search);
      },
      onError: (message) => {
        setMessages([...next, { role: "assistant", content: message, error: true }]);
        setStreaming("");
      },
    });
    setLoading(false);
  }

  const contextPct = contextLimit ? Math.min(100, Math.round((tokens / contextLimit) * 100)) : null;

  return (
    <div className="flex h-[calc(100dvh-9rem)] min-h-[520px] min-w-0 max-w-full gap-3 overflow-hidden lg:gap-4">
      <div className="hidden w-56 shrink-0 flex-col rounded-xl border border-slate-800 bg-slate-900 p-3 md:flex xl:w-64">
        <button
          onClick={novaConversa}
          className="bg-blue-600 hover:bg-blue-700 rounded-lg px-3 py-2 text-sm mb-3 transition-colors"
        >
          + Nova conversa
        </button>
        <input
          value={search}
          onChange={(e) => { setSearch(e.target.value); loadList(e.target.value); }}
          placeholder="Buscar conversas…"
          className="mb-3 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs"
        />
        <div className="flex-1 overflow-y-auto space-y-1">
          {conversations.length === 0 && (
            <p className="text-slate-600 text-xs px-1">Nenhuma conversa</p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => navigate(`/chat-livre/${c.id}`)}
              className={`group flex items-center gap-2 rounded-lg px-3 py-2 text-xs cursor-pointer transition-colors ${
                c.id === conversationId ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"
              }`}
            >
              <span className="flex-1 truncate" title={c.title}>{c.title}</span>
              <button
                onClick={(e) => apagar(c.id, e)}
                className="shrink-0 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity"
                title="Apagar conversa"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="mb-3 flex min-w-0 items-center gap-2 sm:gap-3">
          <h1 className="hidden truncate text-2xl font-bold sm:block sm:text-2xl">Chat livre</h1>
          {active && !renaming && (
            <button
              onClick={() => { setRenaming(true); setRenameValue(active.title); }}
              className="flex min-w-0 items-center gap-1 truncate text-sm text-slate-300 hover:text-white"
              title="Renomear conversa"
            >
              <span className="truncate">{active.title}</span>
              <Pencil className="h-3 w-3 shrink-0" />
            </button>
          )}
          {active && renaming && (
            <span className="flex min-w-0 items-center gap-1">
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") confirmarRenomear();
                  if (e.key === "Escape") setRenaming(false);
                }}
                className="min-w-0 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm"
              />
              <button onClick={confirmarRenomear} title="Confirmar"><Check className="h-4 w-4 text-emerald-400" /></button>
              <button onClick={() => setRenaming(false)} title="Cancelar"><X className="h-4 w-4 text-slate-500" /></button>
            </span>
          )}
          <span className="ml-auto shrink-0 text-xs text-slate-400">
            {tokens.toLocaleString("pt-BR")} tokens
            {contextPct != null && ` · ${contextPct}% do contexto`}
            {cost > 0 && ` · ~US$ ${cost.toFixed(4)}`}
          </span>
        </div>

        <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-800/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>Este chat não consulta o WorkDev; não confie nele para números do sistema.</span>
        </div>

        {contextWarning && (
          <div role="alert" className="mb-3 rounded-lg border border-orange-700 bg-orange-950/50 px-3 py-2 text-xs text-orange-200">
            A conversa passou de ~80% do contexto do modelo local. As mensagens mais antigas serão deixadas de fora para não estourar o contexto.
          </div>
        )}

        <div ref={messagesRef} className="min-h-0 min-w-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto overscroll-contain rounded-xl border border-slate-800 bg-slate-900 p-3 sm:p-4">
          {messages.length === 0 && !streaming && (
            <p className="text-slate-500 text-sm">
              Converse livremente com o modelo escolhido — ideias, rascunhos, assuntos diversos.
              Nada aqui cria ou altera planos, tasks, ADRs ou Knowledge.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i}>
              <MessageBubble msg={m} />
              {m.role === "assistant" && m.model && (
                <p className="mt-1 text-[10px] text-slate-600">{m.model}</p>
              )}
            </div>
          ))}
          {streaming && (
            <div className="max-w-[75%] rounded-2xl rounded-bl-sm bg-slate-800 px-4 py-2.5 text-sm whitespace-pre-wrap">
              {streaming}
            </div>
          )}
          {loading && !streaming && (
            <div className="max-w-[75%] rounded-2xl rounded-bl-sm bg-slate-800 px-4 py-2.5 text-sm text-slate-400">
              Pensando...
            </div>
          )}
        </div>

        <div className="mt-3 flex min-w-0 flex-wrap gap-2 sm:flex-nowrap sm:gap-3">
          <input
            className="min-w-0 flex-[1_1_100%] rounded-lg border border-slate-700 bg-slate-800 px-4 py-3 text-sm sm:flex-1"
            placeholder="Escreva sua mensagem…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && enviar()}
          />
          <select
            aria-label="Fonte de IA"
            value={modelo.label}
            onChange={(e) => {
              const next = MODELOS.find((m) => m.label === e.target.value) || MODELOS[0];
              setCatalogModel("");
              setCatalogModels([]);
              setModelo(next);
            }}
            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-3 text-sm text-slate-300 sm:max-w-48"
          >
            {MODELOS.map((m) => (
              <option key={m.label} value={m.label}>{m.label}</option>
            ))}
          </select>
          {dynamicSource && (
            <select
              aria-label={localSource ? "Modelo local" : "Modelo OpenRouter"}
              value={selectedEntry ? catalogModel : ""}
              disabled={catalogStatus !== "ready" || catalogModels.length === 0}
              onChange={(e) => setCatalogModel(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-3 text-sm text-slate-300 sm:max-w-48"
            >
              <option value="">{catalogStatus === "loading" ? "Carregando modelos…" : "Selecione um modelo"}</option>
              {catalogModels.map((m) => <option key={modelKey(m)} value={modelKey(m)}>{m.label}</option>)}
            </select>
          )}
          <button
            onClick={enviar}
            disabled={loading || !selectedModel}
            className="shrink-0 rounded-lg bg-blue-600 px-5 py-3 transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            Enviar
          </button>
        </div>
        {dynamicSource && catalogStatus === "error" && (
          <p role="alert">Não foi possível carregar os modelos {localSource ? "locais" : "OpenRouter"}.</p>
        )}
      </div>
    </div>
  );
}
