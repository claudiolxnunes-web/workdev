import { useEffect, useState } from "react";
import { getProvidersStatus } from "../../../services/ai.service";
import type { ProviderStatus } from "../../../services/ai.service";

export function AIProvidersTab() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [connected, setConnected] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    getProvidersStatus()
      .then((d) => {
        setProviders(d.providers);
        setConnected(d.connected);
      })
      .catch(() => setError("Erro ao carregar status dos providers"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-1">AI Providers</h2>
      <p className="text-slate-500 text-sm mb-4">
        Configurados via variáveis de ambiente no backend — chaves nunca
        aparecem aqui, só o status de conexão.
      </p>
      {loading && <p className="text-slate-500 text-sm">Carregando...</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!loading && !error && (
        <>
          <p className="text-sm mb-3">{connected} de {providers.length} conectados</p>
          <ul className="space-y-2">
            {providers.map((p) => (
              <li
                key={p.provider}
                className="flex items-center justify-between text-sm bg-slate-800 rounded-lg px-3 py-2"
              >
                <span>{p.label}</span>
                <span>{p.connected ? "🟢 conectado" : "⚫ não configurado"}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
