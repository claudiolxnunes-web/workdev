import { useProject } from "../useProject";

export function DatabaseTab() {
  const project = useProject();

  if (!project.supabase_project) {
    return (
      <p className="text-slate-500 text-sm">
        Nenhum banco Supabase configurado para este projeto.
      </p>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-3">Supabase</h2>
      <p className="text-slate-300">{project.supabase_project}</p>
    </div>
  );
}
