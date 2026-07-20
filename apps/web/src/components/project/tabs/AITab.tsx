import { Link } from "react-router-dom";
import { useProject } from "../ProjectContext";

export function AITab() {
  const project = useProject();

  const sugestoes = [
    `status do projeto ${project.name}`,
    `quais itens high estão pendentes no ${project.name}?`,
    `cria uma task no ${project.slug}: `,
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-2xl">
      <h2 className="text-lg font-bold mb-2">Perguntar ao AI Hub</h2>
      <p className="text-slate-400 text-sm mb-4">
        O AI Hub tem acesso ao backlog e aos projetos do WorkDev via function-calling.
        Ainda não existe uma conversa isolada por projeto — abra o AI Hub e mencione o
        nome ou slug do projeto para dar contexto.
      </p>
      <div className="space-y-2 mb-4">
        {sugestoes.map((s) => (
          <p
            key={s}
            className="text-xs bg-slate-800 rounded-lg px-3 py-2 text-slate-400 font-mono"
          >
            {s}
          </p>
        ))}
      </div>
      <Link
        to="/ai-hub"
        className="inline-block bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors"
      >
        Abrir AI Hub →
      </Link>
    </div>
  );
}
