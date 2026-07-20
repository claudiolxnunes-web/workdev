import { useEffect, useState } from "react";
import { getEngineeringStatus } from "../services/engineering.service";
import type { EngineeringStatus } from "../services/engineering.service";
import { GraphExplorer } from "../components/graph";

const modules = [
  { title: "Architecture", description: "System architecture and technical decisions." },
  { title: "Frontend", description: "React, components and user interfaces." },
  { title: "Backend", description: "APIs, business rules and services." },
  { title: "Database", description: "SQL schemas, Supabase and migrations." },
  { title: "Testing", description: "Unit, integration and end-to-end tests." },
  { title: "DevOps", description: "Docker, CI/CD and infrastructure automation.", live: true },
];

export default function Engineering() {
  const [aberto, setAberto] = useState<string | null>(null);
  const [dados, setDados] = useState<EngineeringStatus | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function carregar() {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await getEngineeringStatus());
    } catch {
      setErro("Falha ao carregar status da infraestrutura.");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    if (aberto === "DevOps") carregar();
  }, [aberto]);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">Engineering</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {modules.map((m) => (
          <div
            key={m.title}
            onClick={() => m.live && setAberto(aberto === m.title ? null : m.title)}
            className={`bg-slate-900 border rounded-xl p-6 ${
              m.live
                ? "border-emerald-700 cursor-pointer hover:border-emerald-500"
                : "border-slate-800 opacity-70"
            } ${aberto === m.title ? "ring-1 ring-emerald-500" : ""}`}
          >
            <h2 className="text-xl font-bold mb-4">
              {m.title}
              {m.live && (
                <span className="ml-2 text-xs text-emerald-400 font-normal">● live</span>
              )}
            </h2>
            <p className="text-slate-400">{m.description}</p>
          </div>
        ))}
      </div>

      {aberto === "DevOps" && (
        <div className="mt-8 bg-slate-900 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-bold">Infraestrutura — VPS1</h2>
            <button
              onClick={carregar}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sm"
            >
              {carregando ? "Atualizando…" : "Atualizar"}
            </button>
          </div>

          {erro && <p className="text-red-400 mb-4">{erro}</p>}

          {dados && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <h3 className="font-semibold mb-3 text-slate-300">Serviços</h3>
                {dados.servicos.map((s) => (
                  <div key={s.nome} className="flex items-center gap-2 py-1">
                    <span className={s.estado === "active" ? "text-emerald-400" : "text-red-400"}>●</span>
                    <span>{s.nome}</span>
                    <span className="text-slate-500 text-sm ml-auto">{s.estado}</span>
                  </div>
                ))}

                <h3 className="font-semibold mb-3 mt-6 text-slate-300">Containers</h3>
                {dados.containers.map((c) => (
                  <div key={c.nome} className="flex items-center gap-2 py-1">
                    <span className={c.estado === "running" ? "text-emerald-400" : "text-red-400"}>●</span>
                    <span>{c.nome}</span>
                    <span className="text-slate-500 text-sm ml-auto">{c.status}</span>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="font-semibold mb-3 text-slate-300">Backups recentes</h3>
                {dados.backups.map((b, i) => (
                  <div key={i} className="flex items-center gap-2 py-1 text-sm">
                    <span className="truncate">{b.arquivo || b.erro}</span>
                    {b.tamanho_mb !== undefined && (
                      <span className="text-slate-500 ml-auto whitespace-nowrap">
                        {b.tamanho_mb} MB · {b.data}
                      </span>
                    )}
                  </div>
                ))}

                <h3 className="font-semibold mb-3 mt-6 text-slate-300">Recursos</h3>
                {dados.recursos.disco && (
                  <p className="text-sm py-1">
                    Disco: {dados.recursos.disco.usado} usado · {dados.recursos.disco.livre} livre ({dados.recursos.disco.pct})
                  </p>
                )}
                {dados.recursos.memoria_mb && (
                  <p className="text-sm py-1">
                    Memória: {dados.recursos.memoria_mb.usada} / {dados.recursos.memoria_mb.total} MB
                  </p>
                )}
                <p className="text-slate-600 text-xs mt-4">Gerado em {dados.gerado_em}</p>
              </div>
            </div>
          )}
        </div>
      )}
    
      <div className="mt-8 bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Engineering Graph</h2>
        <div style={{ height: 520 }}>
          <GraphExplorer project_id="" />
        </div>
      </div>
    </div>
  );
}
