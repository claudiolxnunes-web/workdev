// Workspace — leitura do checkout só por GET (árvore, arquivo, alterações, diff).
// Os POST são da sessão: criam e encerram a cópia isolada, nunca o checkout.
const API_KEY = import.meta.env.VITE_API_KEY || ""
const headers: HeadersInit = { "X-API-Key": API_KEY }

export interface ItemArvore { nome: string; caminho: string; tipo: "pasta" | "arquivo" }
export interface Arvore { pasta: string; itens: ItemArvore[]; truncado: boolean }
export interface Arquivo { caminho: string; binario: boolean; tamanho: number; texto: string; linhas: number; truncado: boolean }
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

export const getArvore = (pasta = "") => get<Arvore>("/arvore", { pasta })
export const getArquivo = (caminho: string) => get<Arquivo>("/arquivo", { caminho })
export const getAlteracoes = () => get<Alteracoes>("/alteracoes")
export const getDiff = (caminho: string) => get<DiffArquivo>("/diff", { caminho })

export interface Sessao {
  id: string; status: "ativa" | "encerrada"; branch: string; caminho: string; base: string
  branch_origem: string; task_id: string | null; chat_session_id: string | null; titulo: string | null
  criada_em: string; encerrada_em: string | null; observacao?: string; alteracoes_descartadas?: number
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
