import { useEffect, useRef, useState } from "react";
import { MessageBubble, type Msg } from "@/components/ai-hub";
import { useProject } from "../useProject";

export function AITab() {
  const project = useProject();
  const storageKey = `workdev_chat_session_${project.slug}`;
  const [messages, setMessages] = useState<Msg[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(
    () => sessionStorage.getItem(storageKey)
  );
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (!sessionId) return;
    (async () => {
      try {
        const r = await fetch(`/api/chat/sessions/${sessionId}`);
        if (!r.ok) return;
        const data = await r.json();
        setMessages(data.messages);
      } catch { /* silencioso */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        body: JSON.stringify({
          messages: next,
          session_id: sessionId,
          project_slug: project.slug,
        }),
      });
      const data = await r.json();
      setMessages([
        ...next,
        { role: "assistant" as const, content: data.reply || "Erro na resposta", error: !!data.error },
      ]);
      if (data.session_id) {
        setSessionId(data.session_id);
        sessionStorage.setItem(storageKey, data.session_id);
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

  function newChat() {
    setMessages([]);
    setSessionId(null);
    sessionStorage.removeItem(storageKey);
  }

  return (
    <div className="flex flex-col h-[calc(100vh-14rem)] max-w-3xl">
      <div className="flex items-center gap-3 mb-3">
        <h2 className="text-lg font-bold">AI — {project.name}</h2>
        <button
          onClick={newChat}
          className="ml-auto text-xs text-slate-400 hover:text-white border border-slate-700 rounded-lg px-3 py-1.5 transition-colors"
        >
          Nova conversa
        </button>
      </div>
      <div className="flex-1 min-w-0 overflow-y-auto space-y-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        {messages.length === 0 && (
          <p className="text-slate-500 text-sm">
            Converse sobre o projeto {project.name} (slug: {project.slug}). O contexto
            e o resumo do backlog já são injetados automaticamente. Ex: "status do
            projeto", "quais itens high estão pendentes?", "cria uma task: ...".
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
      <div className="flex gap-3 mt-4">
        <input
          className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-sm"
          placeholder={`Pergunte sobre ${project.name}...`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          onClick={send}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg transition-colors disabled:opacity-50"
        >
          Enviar
        </button>
      </div>
    </div>
  );
}
