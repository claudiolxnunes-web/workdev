import { startTransition, useEffect, useState } from "react";
import {
  deleteProviderKey,
  getProvidersStatus,
  updateProviderKey,
} from "../../../services/ai.service";
import type { ProviderStatus } from "../../../services/ai.service";

export function AIProvidersTab() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [connected, setConnected] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

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
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-1">AI Providers</h2>
      <p className="text-slate-500 text-sm mb-4">
        As chaves são armazenadas no backend e nunca são exibidas ou devolvidas
        pela API.
      </p>
      {loading && <p className="text-slate-500 text-sm">Carregando...</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!loading && !error && (
        <>
          <p className="text-sm mb-3">{connected} de {providers.length} conectados</p>
          <ul className="space-y-2">
            {providers.map((p) => (
              <li key={p.provider} className="bg-slate-800 rounded-lg px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span>{p.label}</span>
                  <div className="flex items-center gap-2">
                    <span>{p.connected ? "🟢 conectado" : "⚫ não configurado"}</span>
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
  );
}
