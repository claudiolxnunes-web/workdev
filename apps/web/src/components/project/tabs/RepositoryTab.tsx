import { useProject } from "../ProjectContext";

export function RepositoryTab() {
  const project = useProject();

  if (!project.github_url) {
    return (
      <p className="text-slate-500 text-sm">Nenhum repositório configurado.</p>
    );
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-3">GitHub</h2>
      <a
        href={project.github_url}
        target="_blank"
        rel="noreferrer"
        className="text-blue-400 hover:underline break-all"
      >
        {project.github_url}
      </a>
      {(project.dev_branch || project.prod_branch) && (
        <p className="text-slate-400 text-sm mt-3">
          Branches: {project.dev_branch || "?"} → {project.prod_branch || "?"}
        </p>
      )}
    </div>
  );
}
