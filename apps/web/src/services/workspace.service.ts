// Workspace — só GET em /api/workspace/*: árvore, arquivo, alterações e diff do checkout.
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
