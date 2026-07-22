const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.DEV ? "http://localhost:8000" : "");
const API_KEY = import.meta.env.VITE_API_KEY || "";

const headers: HeadersInit = { "X-API-Key": API_KEY };

export async function getProjects() {
  const response = await fetch(`${API_URL}/api/projects`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar projetos");
  return response.json();
}

export async function getProject(slug: string) {
  const response = await fetch(`${API_URL}/api/projects/${slug}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar projeto");
  return response.json();
}

export interface ProjectCreate {
  name: string;
  type: string;
  stack?: string;
  description?: string;
}

export async function createProject(data: ProjectCreate) {
  const response = await fetch(`${API_URL}/api/projects`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || "Erro ao criar projeto");
  }
  return response.json();
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
  status?: string;
  stack?: string;
  vps?: string;
  github_url?: string;
  netlify_project?: string;
  vercel_project?: string;
  supabase_project?: string;
  dev_branch?: string;
  prod_branch?: string;
}

export async function updateProject(slug: string, data: ProjectUpdate) {
  const response = await fetch(`${API_URL}/api/projects/${slug}`, {
    method: "PATCH",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Erro ao atualizar projeto");
  return response.json();
}
