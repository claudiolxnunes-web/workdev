import { startTransition, useEffect, useState } from "react";
import {
  deleteProviderKey,
  getProvidersStatus,
  updateProviderKey,
} from "../../../services/ai.service";
import type { ProviderStatus } from "../../../services/ai.service";

type AgentStatus = {
  agent: string;
  runtime_state: "ONLINE" | "OFFLINE" | "STARTING" | "STOPPING" | "ERROR";
  activity_state: "IDLE" | "BUSY" | "WAITING_INPUT";
  checked_at: string;
  health_reason?: string | null;
};

const AGENT_NAMES: Record<string, string> = {
  claude: "Claude", codex: "Codex", kimi: "Kimi", openrouter: "Qwen",
  gemini: "Gemini", "local-code": "Local Code",
};

const REASONS: Record<string, string> = {
  runtime_inconsistent: "Modelo ou processo presente, mas a sessão do agente não está ativa",
  snapshot_stale: "Leitura do healthcheck atrasada",
  physical_state_unknown: "Estado físico não pôde ser confirmado",
};

function stateLabel(row: AgentStatus): string {
  if (row.runtime_state === "ERROR") return "Erro";
  if (row.runtime_state === "OFFLINE") return "Desligado";
  if (row.runtime_state === "STARTING") return "Ligando";
  if (row.runtime_state === "STOPPING") return "Desligando";
  if (row.activity_state === "BUSY") return "Ligado · ocupado";
  if (row.activity_state === "WAITING_INPUT") return "Ligado · aguardando entrada";
  return "Ligado · ocioso";
}

export function AIProvidersTab() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [connected, setConnected] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [agentsError, setAgentsError] = useState("");

  const load = () => getProvidersStatus().then((d) => {
    setProviders(d.providers);
    setConnected(d.connected);
  });

  useEffect(() => {
    startTransition(() => setLoading(true));
    load()
      .catch(() => setError("Erro ao carregar status dos providers"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let active = true;
    async function loadAgents() {
      try {
        const response = await fetch("/api/agents/status", { cache: "no-store" });
        if (!response.ok) throw new Error("Snapshot indisponível");
        const data = await response.json();
        if (!Array.isArray(data.agents)) throw new Error("Snapshot inválido");
        if (active) {
          setAgents(data.agents.filter((row: AgentStatus) => row.agent in AGENT_NAMES));
          setAgentsError("");
        }
      } catch {
        if (active) { setAgents(null); setAgentsError("Estado dos agentes indisponível"); }
      }
    }
    void loadAgents();
    const timer = window.setInterval(() => { if (!document.hidden) void loadAgents(); }, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function save(provider: string) {
    if (!apiKey.trim()) return;
    setSaving(true);
    setError("");
    try {
      await updateProviderKey(provider, apiKey);
      await load();
      setApiKey("");
      setEditing(null);
    } catch {
      setError("Erro ao salvar chave do provider");
    } finally {
      setSaving(false);
    }
  }

  async function remove(provider: string) {
    setSaving(true);
    setError("");
    try {
      await deleteProviderKey(provider);
      await load();
    } catch {
      setError("Erro ao remover chave do provider");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4 max-w-2xl">
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <h2 className="text-lg font-bold mb-1">AI Providers</h2>
      <p className="text-slate-500 text-sm mb-4">
        Aqui aparece somente se a chave está cadastrada no backend. O estado
        físico dos agentes está abaixo; uma chave cadastrada não indica que a
        CLI esteja ligada.
      </p>
      {loading && <p className="text-slate-500 text-sm">Carregando...</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!loading && !error && (
        <>
          <p className="text-sm mb-3">{connected} de {providers.length} chaves cadastradas</p>
          <ul className="space-y-2">
            {providers.map((p) => (
              <li key={p.provider} className="bg-slate-800 rounded-lg px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span>{p.label}</span>
                  <div className="flex items-center gap-2">
                    <span>{p.connected ? "Chave cadastrada" : "Chave ausente"}</span>
                    <button
                      type="button"
                      className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600"
                      onClick={() => { setEditing(p.provider); setApiKey(""); }}
                    >
                      {p.connected ? "Substituir" : "Configurar"}
                    </button>
                    {p.connected && (
                      <button
                        type="button"
                        disabled={saving}
                        className="rounded px-2 py-1 text-red-300 hover:bg-red-950 disabled:opacity-50"
                        onClick={() => void remove(p.provider)}
                      >
                        Remover
                      </button>
                    )}
                  </div>
                </div>
                {editing === p.provider && (
                  <form
                    className="mt-3 flex gap-2"
                    onSubmit={(event) => { event.preventDefault(); void save(p.provider); }}
                  >
                    <input
                      type="password"
                      autoComplete="new-password"
                      aria-label={`Nova chave para ${p.label}`}
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      className="min-w-0 flex-1 rounded border border-slate-600 bg-slate-950 px-3 py-2"
                      placeholder="Cole a nova chave"
                    />
                    <button
                      type="submit"
                      disabled={saving || !apiKey.trim()}
                      className="rounded bg-indigo-600 px-3 py-2 disabled:opacity-50"
                    >
                      Salvar
                    </button>
                    <button
                      type="button"
                      onClick={() => { setEditing(null); setApiKey(""); }}
                      className="rounded px-3 py-2 text-slate-400"
                    >
                      Cancelar
                    </button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <h3 className="text-lg font-bold mb-1">Estado real dos agentes</h3>
      <p className="text-slate-500 text-sm mb-3">Leitura do healthcheck; atualiza a cada 10 segundos.</p>
      {agentsError && <p role="alert" className="text-red-400 text-sm">{agentsError}</p>}
      {!agentsError && agents === null && <p className="text-slate-500 text-sm">Carregando estado dos agentes…</p>}
      {agents && <ul className="space-y-2" aria-label="Estado real dos agentes">
        {agents.map(row => <li key={row.agent} className="flex flex-wrap items-center justify-between gap-2 rounded bg-slate-800 px-3 py-2 text-sm">
          <span className="font-medium">{AGENT_NAMES[row.agent]}</span>
          <span className={row.runtime_state === "ONLINE" ? "text-emerald-300" : row.runtime_state === "ERROR" ? "text-amber-300" : "text-slate-400"}>
            {stateLabel(row)}
          </span>
          {row.health_reason && <span className="w-full text-xs text-amber-300">Motivo: {REASONS[row.health_reason] ?? row.health_reason}</span>}
          {row.checked_at && <span className="w-full text-xs text-slate-500">Verificado: {new Date(row.checked_at).toLocaleString("pt-BR")}</span>}
        </li>)}
      </ul>}
    </div>
    </div>
  );
}
