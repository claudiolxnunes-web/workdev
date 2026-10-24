// Bancada Local — leitura (GET) e execuções por clique (POST); nada é aplicado ao repositório.
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
  ocupado?: boolean
}

export interface PropostaResumo {
  id: string
  modelo: string
  origem: "rodar" | "corpus" | "pagina"
  origem_de?: string | null
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
  tarefa?: { instrucao: string; trechos: Array<[string, number, number]>; base: string; origem_de?: string | null; prompt_correcao?: string | null } | null
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

// ---------------------------------------------------------------- segunda etapa (POST, por clique)

export interface EventoBancada {
  tipo: "inicio" | "token" | "vigia" | "reinicio" | "fim" | "erro"
  texto?: string
  id?: string
  modelo?: string
  base?: string
  nomes?: string[]
  mensagem?: string
  codigo?: string
  segundos?: number
  tokens?: number | null
  retentativa?: boolean
}

export interface NovaTarefa {
  id: string
  instrucao: string
  trechos: Array<[string, number, number]>
  max_tokens?: number
  exige?: Record<string, string>
  espera_diff?: boolean
}

async function falha(response: Response): Promise<never> {
  let mensagem = `Bancada: HTTP ${response.status}`
  try {
    const corpo = await response.json()
    const detalhe = corpo?.detail
    mensagem = typeof detalhe === "string" ? detalhe : detalhe?.message ?? mensagem
  } catch { /* corpo sem JSON */ }
  throw new Error(mensagem)
}

async function post<T>(caminho: string, corpo?: unknown): Promise<T> {
  const response = await fetch(`/api/bancada${caminho}`, {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify(corpo ?? {}),
  })
  if (!response.ok) return falha(response)
  return response.json() as Promise<T>
}

/** POST que devolve eventos SSE; cada evento chega em onEvento, na ordem. */
async function fluxo(caminho: string, corpo: unknown, onEvento: (evento: EventoBancada) => void): Promise<void> {
  const response = await fetch(`/api/bancada${caminho}`, {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  })
  if (!response.ok) return falha(response)
  const leitor = response.body?.getReader()
  if (!leitor) throw new Error("Bancada: resposta sem fluxo")
  const decodificador = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await leitor.read()
    if (value) buffer += decodificador.decode(value, { stream: true })
    let fimEvento = buffer.indexOf("\n\n")
    while (fimEvento >= 0) {
      const bloco = buffer.slice(0, fimEvento)
      buffer = buffer.slice(fimEvento + 2)
      for (const linha of bloco.split("\n")) {
        if (linha.startsWith("data:")) onEvento(JSON.parse(linha.slice(5).trim()) as EventoBancada)
      }
      fimEvento = buffer.indexOf("\n\n")
    }
    if (done) break
  }
}

export const ligarModelo = (acao: "ligar" | "desligar") => post<{ acao: string; ok: boolean }>(`/modelo/${acao}`)
export const rodarTarefa = (tarefa: NovaTarefa, onEvento: (e: EventoBancada) => void) => fluxo("/rodar", tarefa, onEvento)
export const reenviarProposta = (modelo: string, id: string, prompt: string, onEvento: (e: EventoBancada) => void) =>
  fluxo(`/propostas/${encodeURIComponent(modelo)}/${encodeURIComponent(id)}/reenviar`, { prompt }, onEvento)
export const verificarProposta = (modelo: string, id: string) =>
  post<{ achados: Achado[]; erros: number; aprovada: boolean }>(`/propostas/${encodeURIComponent(modelo)}/${encodeURIComponent(id)}/verificar`)
export interface Observers {
  padrao: string
  observers: string[]
  segunda_opiniao: { id: string; primario: string; arbitro: string }
}
export const getObservers = () => get<Observers>("/observers")

export interface ResultadoParecer {
  ok: boolean
  parecer: { veredito: Veredito } | null
  custo_usd: number | null
  falhas: string[]
  /** Só no modo segunda opinião: quem deu a palavra final e por onde passou. */
  decidido_por?: string | null
  etapas?: Array<{ observer: string; ok: boolean; veredito: Veredito | null }>
}
export const pedirParecer = (modelo: string, id: string, observer?: string) =>
  post<ResultadoParecer>(
    `/propostas/${encodeURIComponent(modelo)}/${encodeURIComponent(id)}/parecer`, observer ? { observer } : {})

/** Lote colado do AI Hub: lista de tarefas ou {"tarefas": [...]}. */
export function lerLote(texto: string): NovaTarefa[] {
  const dados = JSON.parse(texto)
  const lista = Array.isArray(dados) ? dados : dados?.tarefas
  if (typeof dados?.fora_do_alcance === "string" && !lista?.length) throw new Error(`o planejador recusou: ${dados.fora_do_alcance}`)
  if (!Array.isArray(lista) || lista.length === 0) throw new Error("o JSON precisa ser uma lista de tarefas")
  return lista.map((t, i) => {
    if (!t || typeof t.id !== "string" || typeof t.instrucao !== "string" || !Array.isArray(t.trechos)) {
      throw new Error(`tarefa ${i + 1}: precisa de id, instrucao e trechos`)
    }
    return { id: t.id, instrucao: t.instrucao, trechos: t.trechos, max_tokens: t.max_tokens,
             exige: t.exige, espera_diff: t.espera_diff }
  })
}

/** Plano validado no AI Hub -> lote(s) gravados em tmp/bancada/planos/ (11 a 20 tarefas viram 2 lotes). */
export const gravarLote = (plano: unknown) =>
  post<{ lotes: Array<{ lote: string; tarefas: number }> }>("/lotes", { plano })
export const lerLoteGravado = (lote: string) =>
  get<{ lote: string; tarefas: NovaTarefa[] }>(`/lotes/${encodeURIComponent(lote)}`)

/** O bloco ```json do chat é um plano da Bancada? Devolve o plano ou null. */
export function planoDaBancada(codigo: string): { tarefas: unknown[] } | null {
  try {
    const dados = JSON.parse(codigo)
    return dados && Array.isArray(dados.tarefas) && dados.tarefas.length > 0 ? dados : null
  } catch { return null }
}
