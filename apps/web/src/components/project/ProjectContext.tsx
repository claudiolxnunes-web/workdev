import { startTransition, useCallback, useEffect, useState } from "react";
import { getProject } from "../../services/projects.service";
import { ProjectContext } from "./projectContextInstance";

export interface ProjectData {
  id: string;
  name: string;
  slug: string;
  description?: string;
  type: string;
  status: string;
  stack?: string;
  vps?: string;
  github_url?: string;
  netlify_project?: string;
  vercel_project?: string;
  supabase_project?: string;
  dev_branch?: string;
  prod_branch?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectContextValue extends ProjectData {
  refresh: () => void;
}

export function ProjectProvider({
  slug,
  children,
}: {
  slug: string;
  children: React.ReactNode;
}) {
  const [project, setProject] = useState<ProjectData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    getProject(slug)
      .then((p: ProjectData) => setProject(p))
      .catch(() => setError("Projeto não encontrado"))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    startTransition(() => {
      setLoading(true);
      setError("");
    });
    getProject(slug)
      .then((p: ProjectData) => setProject(p))
      .catch(() => setError("Projeto não encontrado"))
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) {
    return <p className="text-slate-400">Carregando projeto...</p>;
  }
  if (error || !project) {
    return <p className="text-red-400">{error || "Projeto não encontrado"}</p>;
  }

  return (
    <ProjectContext.Provider value={{ ...project, refresh: load }}>
      {children}
    </ProjectContext.Provider>
  );
}

