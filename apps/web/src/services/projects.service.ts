const API_URL = "";
  import.meta.env.VITE_API_URL ||
  "http://localhost:8000";
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
