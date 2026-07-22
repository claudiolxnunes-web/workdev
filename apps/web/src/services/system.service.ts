const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

export interface MigrationStatus {
  current: string | null;
  head: string | null;
  up_to_date: boolean;
}

export async function getMigrationStatus(): Promise<MigrationStatus> {
  const response = await fetch("/api/system/migrations", { headers });
  if (!response.ok) throw new Error("Erro ao buscar status de migrações");
  return response.json();
}
