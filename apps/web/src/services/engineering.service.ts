const API_URL = import.meta.env.VITE_API_URL || "";
const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface Servico {
  nome: string;
  estado: string;
}

export interface Container {
  nome: string;
  estado: string;
  status: string;
}

export interface Backup {
  arquivo?: string;
  tamanho_mb?: number;
  data?: string;
  erro?: string;
}

export interface Recursos {
  disco?: { usado: string; livre: string; pct: string };
  memoria_mb?: { total: string; usada: string; livre: string };
}

export interface EngineeringStatus {
  gerado_em: string;
  servicos: Servico[];
  containers: Container[];
  backups: Backup[];
  recursos: Recursos;
}

export async function getEngineeringStatus(): Promise<EngineeringStatus> {
  const response = await fetch(`${API_URL}/api/engineering/status`, { headers });
  if (!response.ok) throw new Error("Erro ao buscar status");
  return response.json();
}

export async function getEngineeringGraphLabels(
  projectId?: string,
): Promise<Record<string, string>> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const response = await fetch(
    `${API_URL}/api/engineering/graph/labels${query}`,
    { headers },
  );
  if (!response.ok) throw new Error("Erro ao buscar títulos do grafo");
  const body = await response.json() as { labels: Record<string, string> };
  return body.labels;
}
