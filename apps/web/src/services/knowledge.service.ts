const API_URL = import.meta.env.VITE_API_URL || "";
const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface KnowledgeEntry {
  id: string;
  title: string;
  content: string;
  category: "decisao" | "licao" | "solucao" | "referencia";
  tags: string | null;
  created_at: string;
}

export async function getKnowledge(
  categoria?: string,
  termo?: string
): Promise<KnowledgeEntry[]> {
  const params = new URLSearchParams();
  if (categoria) params.set("categoria", categoria);
  if (termo) params.set("termo", termo);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_URL}/api/knowledge${qs}`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar conhecimento");
  return response.json();
}
