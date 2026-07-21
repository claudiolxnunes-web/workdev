import { useEffect, useState } from "react";

interface HealthStatus {
  service: string;
  version: string;
  status: string;
}

export function SistemaTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("Erro ao consultar o status do backend"));
  }, []);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-4">Sistema</h2>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!error && !health && <p className="text-slate-500 text-sm">Carregando...</p>}
      {health && (
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Serviço</dt>
            <dd>{health.service}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Versão</dt>
            <dd>{health.version}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Status</dt>
            <dd>
              {health.status === "online" ? "🟢" : "🔴"} {health.status}
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
