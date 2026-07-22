import { Link } from "react-router-dom";
import { useProject } from "./useProject";

const STATUS_COLORS: Record<string, string> = {
  Production: "bg-green-700",
  Development: "bg-blue-700",
  Planning: "bg-slate-600",
};

export function ProjectHeader() {
  const project = useProject();

  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <Link to="/projects" className="text-sm text-slate-500 hover:text-slate-300">
          ← Projects
        </Link>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-4xl font-bold">{project.name}</h1>
          <span
            className={`text-xs px-2 py-1 rounded ${
              STATUS_COLORS[project.status] || "bg-slate-700"
            }`}
          >
            {project.status}
          </span>
        </div>
        {project.description && (
          <p className="text-slate-400 text-lg mt-2">{project.description}</p>
        )}
      </div>
    </div>
  );
}
