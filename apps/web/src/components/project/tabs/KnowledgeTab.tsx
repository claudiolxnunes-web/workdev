import { useEffect, useState } from "react";
import { useProject } from "../ProjectContext";
import { getKnowledge } from "../../../services/knowledge.service";
import type { KnowledgeEntry } from "../../../services/knowledge.service";

const COR_BADGE: Record<string, string> = {
  decisao: "bg-blue-600/20 text-blue-400 border-blue-600/40",
  licao: "bg-amber-600/20 text-amber-400 border-amber-600/40",
  solucao: "bg-emerald-600/20 text-emerald-400 border-emerald-600/40",
  referencia: "bg-purple-600/20 text-purple-400 border-purple-600/40",
};

const LABEL: Record<string, string> = {
  decisao: "decisão",
  licao: "lição",
  solucao: "solução",
  referencia: "referência",
};

export function KnowledgeTab() {
  const project = useProject();
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [aberto, setAberto] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getKnowledge(undefined, undefined, project.id)
      .then(setEntries)
      .finally(() => setLoading(false));
  }, [project.id]);

  if (loading) return <p className="text-slate-400">Carregando...</p>;

  if (entries.length === 0) {
    return (
      <p className="text-slate-500 text-sm">
        Nenhuma entrada de conhecimento vinculada a este projeto.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {entries.map((e) => (
        <div
          key={e.id}
          onClick={() => setAberto(aberto === e.id ? null : e.id)}
          className="bg-slate-900 border border-slate-800 rounded-xl p-6 cursor-pointer hover:border-slate-600 transition"
        >
          <div className="flex items-center justify-between mb-3">
            <span
              className={`text-xs px-2 py-0.5 rounded-full border ${COR_BADGE[e.category]}`}
            >
              {LABEL[e.category]}
            </span>
            <span className="text-xs text-slate-600">{e.created_at.slice(0, 10)}</span>
          </div>
          <h2 className="text-lg font-bold mb-2">{e.title}</h2>
          <p
            className={`text-slate-400 text-sm whitespace-pre-wrap ${
              aberto === e.id ? "" : "line-clamp-3"
            }`}
          >
            {e.content}
          </p>
        </div>
      ))}
    </div>
  );
}
