// Bancada Local — MVP somente leitura: só GET em /api/bancada/*.
const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = { "X-API-Key": API_KEY }

export type Severidade = "erro" | "aviso" | "info"
export type Veredito = "aproveitada" | "correcao_pequena" | "descartada" | "falhou"

export interface EstadoBancada {
  ativo: boolean | null
  chave: string | null
  modelo: string | null
  memoria: { total_mb: number | null; disponivel_mb: number | null }
  processo_mb: number | null
  pasta: string
  pasta_existe: boolean
}

export interface PropostaResumo {
  id: string
  modelo: string
  origem: "rodar" | "corpus"
  segundos: number | null
  tokens: number | null
  verificado: boolean
  esperado?: string | null
  achados: Record<Severidade, number> | null
  observers: Array<{ observer: string; veredito: Veredito }>
}

export interface Achado { categoria: string; severidade: Severidade; mensagem: string }

export interface Parecer {
  observer: string
  ok: boolean
  veredito: Veredito | null
  erros: Array<{ categoria?: string; descricao?: string }>
  prompt_correcao: string
  custo_usd: number | null
  segundos: number | null
  falhas: string[]
  data?: string
}

export interface PropostaDetalhe {
  id: string
  modelo: string
  texto: string
  verificacao: { achados: Achado[]; erros: number; aprovada: boolean; tarefa?: string; esperado?: string; data?: string } | null
  pareceres: Parecer[]
}

export interface LinhaResumo {
  modelo: string
  avaliado_por: string
  tarefas: number
  aproveitada: number
  correcao_pequena: number
  descartada: number
  falhas: number
  tempo_medio_s: number | null
}

async function get<T>(caminho: string): Promise<T> {
  const response = await fetch(`/api/bancada${caminho}`, { headers })
  if (!response.ok) throw new Error(`Bancada: HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export const getEstado = () => get<EstadoBancada>("/estado")
export const getPropostas = () => get<{ propostas: PropostaResumo[] }>("/propostas").then((d) => d.propostas)
export const getProposta = (modelo: string, id: string) =>
  get<PropostaDetalhe>(`/propostas/${encodeURIComponent(modelo)}/${encodeURIComponent(id)}`)
export const getResumo = () => get<{ linhas: LinhaResumo[] }>("/resumo").then((d) => d.linhas)
