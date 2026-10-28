// Workspace — leitura do checkout só por GET (árvore, arquivo, alterações, diff).
// Os POST são da sessão: criam e encerram a cópia isolada, nunca o checkout.
const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = { "X-API-Key": API_KEY }

export interface ItemArvore { nome: string; caminho: string; tipo: "pasta" | "arquivo" }
export interface Arvore { pasta: string; itens: ItemArvore[]; truncado: boolean }
export interface Arquivo {
  caminho: string; binario: boolean; tamanho: number; texto: string; linhas: number; truncado: boolean
  /** Do conteúdo inteiro em disco; o salvar recusa se o arquivo mudou depois de aberto. */
  sha256?: string | null
  /** O texto mostrado teve chave mascarada: não é o do disco e não pode ser salvo. */
  mascarado?: boolean
}
export interface Alteracao { caminho: string; estado: string; mais: number | null; menos: number | null }
export interface Alteracoes { base: string; itens: Alteracao[]; truncado: boolean }
export interface DiffArquivo { caminho: string; diff: string; truncado: boolean }

async function get<T>(caminho: string, params?: Record<string, string>): Promise<T> {
  const query = params ? `?${new URLSearchParams(params)}` : ""
  const response = await fetch(`/api/workspace${caminho}${query}`, { headers })
  if (!response.ok) {
    let mensagem = `Workspace: HTTP ${response.status}`
    try {
      const detalhe = (await response.json())?.detail
      mensagem = typeof detalhe === "string" ? detalhe : detalhe?.message ?? mensagem
    } catch { /* corpo sem JSON */ }
    throw new Error(mensagem)
  }
  return response.json() as Promise<T>
}

// Com `sessao`, a leitura vem da cópia da sessão ativa; sem, do checkout.
const comSessao = (params: Record<string, string>, sessao?: string | null) => (sessao ? { ...params, sessao } : params)
export const getArvore = (pasta = "", sessao?: string | null) => get<Arvore>("/arvore", comSessao({ pasta }, sessao))
export const getArquivo = (caminho: string, sessao?: string | null) => get<Arquivo>("/arquivo", comSessao({ caminho }, sessao))
export const getAlteracoes = (sessao?: string | null) => get<Alteracoes>("/alteracoes", comSessao({}, sessao))
export const getDiff = (caminho: string, sessao?: string | null) => get<DiffArquivo>("/diff", comSessao({ caminho }, sessao))

export type StatusFatia = "pendente" | "rodando" | "ok" | "falhou" | "pulada" | "simulada" | "revertida"
export type LinhaBanco = Record<string, unknown>
export interface SimulacaoBanco {
  comando: "INSERT" | "UPDATE" | "DELETE"; tabela: string; linhas: number; ids: string[]
  antes: LinhaBanco[]; depois: LinhaBanco[]; passou: boolean; sql: string
  verificacoes: Array<{ consulta: string; passou: boolean; valor: unknown; erro?: string }>
}
export interface CheckGate { nome: string; passou: boolean; motivo: string; ms: number }
export interface Fatia {
  n: number; id: string; objetivo: string; instrucao: string; trechos: Array<[string, number, number]>
  gate: string[]; exige: Record<string, string>; max_tokens: number
  status: StatusFatia; etapa: string | null; erro: string | null; tentativas: number
  commit: string | null; subtask_id: string | null; gate_checks: CheckGate[]; arquivos?: string[]
  proposta?: { modelo: string; id: string; segundos?: number; leituras?: number } | null
  /** Fatia de banco: SQL proposto, simulação (rollback) e o que foi aplicado. */
  tipo?: "codigo" | "banco"; tabelas?: string[]; verificacao?: string[]; sql?: string | null
  simulacao?: SimulacaoBanco | null
  banco?: { comando: string; tabela: string; linhas: number; aplicado_em: string; trilha: string; revertido_em?: string } | null
}
export interface Sessao {
  id: string; status: "ativa" | "encerrada" | "incorporada"; branch: string; caminho: string; base: string
  branch_origem: string; task_id: string | null; chat_session_id: string | null; titulo: string | null
  criada_em: string; encerrada_em: string | null; observacao?: string; alteracoes_descartadas?: number
  plano?: { aprovado_em: string; fatias: Fatia[] } | null
  commit_incorporado?: string; modo_incorporacao?: "merge" | "squash"
}
export interface EstadoSessao extends Sessao {
  commits: Array<{ sha: string; mensagem: string }>
  alteracoes: Array<{ status: string; caminho: string }>
}
export interface DiffSessao { id: string; diff: string; nao_rastreados: string[]; truncado: boolean }

async function post<T>(caminho: string, corpo: unknown): Promise<T> {
  const response = await fetch(`/api/workspace${caminho}`, {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  })
  if (!response.ok) {
    let mensagem = `Workspace: HTTP ${response.status}`
    let codigo = ""
    try {
      const detalhe = (await response.json())?.detail
      mensagem = typeof detalhe === "string" ? detalhe : detalhe?.message ?? mensagem
      codigo = detalhe?.code ?? ""
    } catch { /* corpo sem JSON */ }
    throw Object.assign(new Error(mensagem), { codigo })
  }
  return response.json() as Promise<T>
}

export const getSessoes = () => get<{ ativa: Sessao | null; recentes: Sessao[] }>("/sessao")
export const getEstadoSessao = (id: string) => get<EstadoSessao>(`/sessao/${encodeURIComponent(id)}`)
export const getDiffSessao = (id: string) => get<DiffSessao>(`/sessao/${encodeURIComponent(id)}/diff`)
export const criarSessao = (dados: { task_id?: string | null; chat_session_id?: string | null; titulo?: string | null }) =>
  post<Sessao>("/sessao", dados)
export const encerrarSessao = (id: string, descartarAlteracoes = false) =>
  post<Sessao>(`/sessao/${encodeURIComponent(id)}/encerrar`, { descartar_alteracoes: descartarAlteracoes })
/** Edição do editor: grava na cópia da sessão e vira commit com o nome do operador. */
export const salvarArquivoSessao = (id: string, caminho: string, texto: string, sha256: string) =>
  post<{ caminho: string; commit: string; sha256: string }>(`/sessao/${encodeURIComponent(id)}/arquivo`, { caminho, texto, sha256 })
export const aprovarPlano = (id: string, plano: unknown) => post<Sessao>(`/sessao/${encodeURIComponent(id)}/plano`, { plano })

/** Sessão de supervisor para um pedido livre do chat do Workspace.
 *
 *  Sem isto, o primeiro texto digitado no painel Supervisor caía numa sessão
 *  genérica do AI Hub (modo "Planejar"), cujo system prompt manda o modelo
 *  responder como planejador do WorkDev — em prosa, sem o bloco ```json do
 *  contrato do Workspace. O cartão "Aprovar plano" nunca aparecia.
 *
 *  Aqui a sessão nasce no modo "Observar" com o protocolo do Workspace já
 *  persistido: o supervisor lê os arquivos, fatia e devolve o plano em JSON. */
export const criarSessaoSupervisor = (prompt: string) =>
  fetch("/api/chat/workspace/planejar", {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  }).then(async (response) => {
    if (!response.ok) {
      const detalhe = await response.json().catch(() => ({}))
      const mensagem = typeof detalhe?.detail === "string" ? detalhe.detail
        : "Não foi possível abrir a sessão do supervisor."
      throw new Error(mensagem)
    }
    return response.json() as Promise<{ id: string; authority: string }>
  })
export const simularBanco = (id: string, n: number, sql: string) =>
  post<Sessao>(`/sessao/${encodeURIComponent(id)}/fatias/${n}/banco/simular`, { sql })
export const aplicarBanco = (id: string, n: number) => post<Sessao>(`/sessao/${encodeURIComponent(id)}/fatias/${n}/banco/aplicar`, {})
export const reverterBanco = (id: string, n: number, forcar = false) =>
  post<Sessao>(`/sessao/${encodeURIComponent(id)}/fatias/${n}/banco/reverter`, { forcar })
export const pularFatia = (id: string, n: number) => post<Sessao>(`/sessao/${encodeURIComponent(id)}/fatias/${n}/pular`, {})
/** Sessão encerrada ou incorporada cujo branch ainda existe (fica para inspeção até o operador apagar). */
export interface SessaoAnterior {
  id: string; status: "encerrada" | "incorporada"; branch: string; branch_origem: string; titulo: string | null
  task_id: string | null; criada_em: string; encerrada_em: string | null; nao_incorporados: number | null
}
export const getSessoesAnteriores = () => get<SessaoAnterior[]>("/sessao/anteriores")
export const apagarBranchSessao = (id: string, perderCommits: boolean) =>
  post<Sessao>(`/sessao/${encodeURIComponent(id)}/apagar-branch`, { perder_commits: perderCommits })

/** Gasto da sessão: o que o modelo local já usou, o que cada fatia aberta deve usar e o custo do supervisor. */
export interface MedicaoSessao {
  sessao: string; taxa_prefill_tok_s: number; taxa_origem: "medida" | "padrao"
  fatias: Array<{
    n: number; status: StatusFatia; gate_s: number
    real: { prefill_s: number; geracao_s: number; prompt_tok: number; cache_tok: number; geracao_tok: number } | null
    previsto: { tokens: number; prefill_s: number } | null
  }>
  total_local: { prefill_s: number; geracao_s: number; prompt_tok: number; geracao_tok: number; leituras: number; tentativas: number }
  supervisor: { chamadas: number; tokens_entrada: number; tokens_saida: number; custo_usd: number; segundos: number } | null
}
export const getMedicaoSessao = (id: string) => get<MedicaoSessao>(`/sessao/${encodeURIComponent(id)}/medicao`)
export const incorporarSessao = (id: string, modo: "merge" | "squash") =>
  post<Sessao>(`/sessao/${encodeURIComponent(id)}/incorporar`, { modo })

/** Evento do fluxo de uma fatia: os do modelo local (token, ferramenta…) mais etapa, gate e fatia. */
export interface EventoFatia {
  tipo: string; n?: number; etapa?: string; status?: StatusFatia; erro?: string; commit?: string
  texto?: string; nome?: string; argumentos?: Record<string, unknown>; caracteres?: number; recusada?: boolean
  checks?: CheckGate[]; codigo?: string; mensagem?: string; segundos?: number; leituras?: number
  /** Parecer do observer sobre a proposta (auditoria antes do commit). */
  parecer?: { ok?: boolean; parecer?: { veredito?: string; erros?: Array<{ descricao?: string }>; prompt_correcao?: string } }
  /** Correção que o supervisor escreveu para a próxima tentativa. */
  correcao?: string
}

/** Executa a fatia n; cada evento SSE chega em onEvento, na ordem. */
export async function executarFatia(id: string, n: number, correcao: string | null, onEvento: (e: EventoFatia) => void): Promise<void> {
  const response = await fetch(`/api/workspace/sessao/${encodeURIComponent(id)}/fatias/${n}/executar`, {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify({ correcao }),
  })
  if (!response.ok) throw new Error(`Workspace: HTTP ${response.status}`)
  const leitor = response.body?.getReader()
  if (!leitor) throw new Error("Workspace: resposta sem fluxo")
  const decodificador = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await leitor.read()
    if (value) buffer += decodificador.decode(value, { stream: true })
    let fim = buffer.indexOf("\n\n")
    while (fim >= 0) {
      const bloco = buffer.slice(0, fim)
      buffer = buffer.slice(fim + 2)
      for (const linha of bloco.split("\n")) {
        if (linha.startsWith("data:")) onEvento(JSON.parse(linha.slice(5).trim()) as EventoFatia)
      }
      fim = buffer.indexOf("\n\n")
    }
    if (done) break
  }
}
