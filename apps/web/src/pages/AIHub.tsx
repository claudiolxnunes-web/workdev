import { useState, useRef, useEffect } from "react";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

export default function AIHub() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

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
        body: JSON.stringify({ messages: next }),
      });
      const data = await r.json();
      setMessages([
        ...next,
        { role: "assistant" as const, content: data.reply || "Erro na resposta" },
      ]);
    } catch {
      setMessages([
        ...next,
        { role: "assistant" as const, content: "Erro ao falar com a API" },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <h1 className="text-3xl font-bold mb-4">AI Hub</h1>

      <div className="flex-1 overflow-y-auto space-y-4 bg-slate-900 border border-slate-800 rounded-xl p-4">
        {messages.length === 0 && (
          <p className="text-slate-500 text-sm">
            Converse com o WorkDev. Ex: "quantos itens high estão pendentes?",
            "cria uma task no nutrigestor: ajustar favicon", "status dos projetos"
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-xl px-4 py-2 whitespace-pre-wrap text-sm ${
              m.role === "user"
                ? "bg-blue-600 ml-auto"
                : "bg-slate-800"
            }`}
          >
            {m.content}
          </div>
        ))}
        {loading && (
          <div className="bg-slate-800 rounded-xl px-4 py-2 text-sm text-slate-400 max-w-[85%]">
            Pensando...
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="flex gap-3 mt-4">
        <input
          className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-sm"
          placeholder="Pergunte ou peça algo ao WorkDev..."
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
