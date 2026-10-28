import { useCallback, useEffect, useRef, useState } from "react";
import { getLocalModels, getOpenRouterModels, sendAiChatWithConfirmation, type CatalogModel } from "@/services/ai.service";
import { criarSessaoSupervisor } from "@/services/workspace.service";
import { planoDoTexto, type PlanoSupervisor } from "./plano";

// Chat do supervisor do Workspace Local: o modelo grande (OpenRouter) que
// planeja o trabalho e acompanha a execução. Fica no painel lateral, como o
// chat do Copilot no VS Code.
//
// Diferente do ChatLocal (que conversa com o modelo local da Bancada), aqui o
// supervisor é quem tem as ferramentas de leitura do repo (`ler_trecho`): é ele
// que localiza os arquivos e fatia o pedido antes do modelo local agir.

const CHAVE_MODELO = "workdev_workspace_supervisor_model";
// Padrão do supervisor (decisão do operador, 2026-10-25): o mais barato. Troca
// para Luna quando o plano sair ruim; a troca fica guardada.
const MODELO_PADRAO = "deepseek/deepseek-v4-flash";
const PROMPT_INICIO = "Faça primeiro a triagem só com ler_task: se a task não couber no Workspace Local (discovery, várias camadas, arquitetura, migração de banco), responda já com fora_do_alcance, sem ler código. Se couber, ache os arquivos com buscar_texto e leia os envolvidos com vários ler_trecho na mesma rodada, fatie em fatias com objetivo único e gate próprio, e entregue o plano em um bloco ```json. Ao recusar, diga por quê para o operador usar o fluxo de nuvem.";

// Modelos locais têm runtime_id: a chave precisa dele, senão dois runtimes com o
// mesmo nome de modelo colidem no seletor.
const chaveModelo = (m: CatalogModel) => (m.runtime_id ? JSON.stringify([m.runtime_id, m.model]) : m.model);

interface Mensagem { role: "user" | "assistant" | "system"; content: string; error?: boolean }

function PlanoNaResposta({ plano, onAprovar }: { plano: PlanoSupervisor; onAprovar: (plano: PlanoSupervisor) => Promise<void> }) {
  const [estado, setEstado] = useState<"livre" | "enviando" | "aprovado">("livre");
  const [erro, setErro] = useState("");
  const objetivos = plano.fatias.map((f, i) => {
    const objetivo = (f as { objetivo?: unknown })?.objetivo;
    return `${i + 1}. ${typeof objetivo === "string" ? objetivo : "(sem objetivo)"}`;
  });
  async function aprovar() {
    setEstado("enviando"); setErro("");
    try { await onAprovar(plano); setEstado("aprovado"); }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "falha ao aprovar"); setEstado("livre"); }
  }
  return (
    <div aria-label="Plano do supervisor" className="mt-2 rounded border border-emerald-900 bg-emerald-950/30 p-2 text-xs">
      <p className="font-semibold text-emerald-200">Plano com {plano.fatias.length} fatia(s)</p>
      <ul className="mt-1 space-y-0.5 text-slate-300">{objetivos.map((o) => <li key={o}>{o}</li>)}</ul>
      <button type="button" disabled={estado !== "livre"} onClick={() => void aprovar()}
        className="mt-2 rounded bg-emerald-700 px-3 py-1 text-white hover:bg-emerald-600 disabled:opacity-60">
        {estado === "enviando" ? "Aprovando…" : estado === "aprovado" ? "Plano aprovado ✓" : "Aprovar plano"}
      </button>
      {erro && <p role="alert" className="mt-1 text-rose-300">{erro}</p>}
    </div>
  );
}

export function ChatSupervisor({ sessionId, onSessionId, onAprovarPlano }: {
  sessionId: string | null;
  onSessionId?: (id: string | null) => void;
  /** Aprovar o plano de uma resposta: vira o plano da sessão (e subtasks da task). */
  onAprovarPlano?: (plano: PlanoSupervisor) => Promise<void>;
}) {
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [entrada, setEntrada] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [modelos, setModelos] = useState<CatalogModel[]>([]);
  const [modelo, setModelo] = useState("");
  const [autoridade, setAutoridade] = useState("");
  const painel = useRef<HTMLDivElement>(null);
  const iniciou = useRef(false);

  // O supervisor pode ser qualquer modelo: os grandes da nuvem e os locais.
  // A escolha fica guardada; sem isso, cada sessão volta ao primeiro da lista.
  useEffect(() => {
    let ativo = true;
    Promise.allSettled([getOpenRouterModels(), getLocalModels()])
      .then(([remotos, locais]) => {
        if (!ativo) return;
        const lista = [
          ...(remotos.status === "fulfilled" ? remotos.value : []),
          ...(locais.status === "fulfilled" ? locais.value : []),
        ];
        setModelos(lista);
        let guardado = "";
        try { guardado = localStorage.getItem(CHAVE_MODELO) || ""; } catch { /* sem storage */ }
        const padrao = lista.find((m) => m.model === MODELO_PADRAO) ?? lista[0];
        const escolhido = lista.find((m) => chaveModelo(m) === guardado) ? guardado : (padrao ? chaveModelo(padrao) : "");
        setModelo(escolhido);
      })
      .catch(() => { if (ativo) setErro("Não foi possível carregar os modelos do supervisor."); });
    return () => { ativo = false; };
  }, []);

  useEffect(() => {
    if (!sessionId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMensagens([]);
      return;
    }
    let ativo = true;
    fetch(`/api/chat/sessions/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("sessão"))))
      .then((data) => {
        if (!ativo) return;
        setMensagens(data.messages ?? []);
        setAutoridade(data.authority ?? "");
      })
      .catch(() => { if (ativo) setErro("Não foi possível carregar a sessão do supervisor."); });
    return () => { ativo = false; };
  }, [sessionId]);

  useEffect(() => {
    const alvo = painel.current;
    if (alvo) alvo.scrollTop = alvo.scrollHeight;
  }, [mensagens, carregando]);

  const enviar = useCallback(async (texto: string, historico?: Mensagem[]) => {
    const atual = historico ?? mensagens;
    const proximas: Mensagem[] = [...atual, { role: "user", content: texto }];
    setMensagens(proximas);
    setCarregando(true);
    setErro("");
    const alvo = modelos.find((m) => chaveModelo(m) === modelo);
    let sessao = sessionId;
    try {
      // Pedido livre, sem sessão: ela precisa nascer como sessão de SUPERVISOR
      // (modo Observar, com o contrato do plano no system prompt). Numa sessão
      // genérica do AI Hub o supervisor responde como planejador do WorkDev —
      // em prosa, sem bloco ```json — e o cartão "Aprovar plano" não aparece.
      if (!sessao) {
        const criada = await criarSessaoSupervisor(texto);
        sessao = criada.id;
      }
      const data = await sendAiChatWithConfirmation({
        messages: proximas,
        session_id: sessao,
        provider: alvo?.provider ?? "openrouter",
        model: alvo?.model ?? modelo,
        ...(alvo?.runtime_id ? { runtime_id: alvo.runtime_id } : {}),
      });
      if (data.authority) setAutoridade(data.authority);
      setMensagens([
        ...proximas,
        { role: "assistant", content: data.reply || "Erro na resposta", error: !!data.error },
      ]);
      if (data.session_id && data.session_id !== sessao) onSessionId?.(data.session_id);
      else if (sessao && sessao !== sessionId) onSessionId?.(sessao);
    } catch {
      setMensagens([...proximas, { role: "assistant", content: "Erro ao falar com o supervisor", error: true }]);
    } finally {
      setCarregando(false);
    }
  }, [mensagens, modelo, modelos, sessionId, onSessionId]);

  // Autostart: a sessão vem pronta do backlog (com a ficha da task no prompt do
  // supervisor) e esta mensagem dispara a triagem e a leitura dos arquivos.
  useEffect(() => {
    if (!sessionId || !modelo || iniciou.current) return;
    if (!new URLSearchParams(window.location.search).get("autostart")) return;
    iniciou.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void enviar(PROMPT_INICIO, []);
    window.history.replaceState({}, "", window.location.pathname);
  }, [sessionId, modelo, enviar]);

  function submeter(evento: React.FormEvent) {
    evento.preventDefault();
    const texto = entrada.trim();
    if (!texto || carregando || !modelo) return;
    setEntrada("");
    void enviar(texto);
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900 px-2 py-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Supervisor</h2>
        <select
          aria-label="Modelo do supervisor"
          value={modelo}
          onChange={(e) => {
            setModelo(e.target.value);
            try { localStorage.setItem(CHAVE_MODELO, e.target.value); } catch { /* sem storage */ }
          }}
          className="min-w-0 flex-1 rounded bg-slate-950 px-1 py-0.5 text-xs text-slate-200"
        >
          {modelos.length === 0 && <option value="">carregando…</option>}
          {modelos.map((m) => (
            <option key={chaveModelo(m)} value={chaveModelo(m)}>
              {m.label || m.model}{m.runtime_id ? ` · ${m.runtime_id}` : ""}
            </option>
          ))}
        </select>
        {autoridade && (
          <span title={`Autoridade da sessão: ${autoridade}`} className="text-[10px] text-slate-500">
            {autoridade}
          </span>
        )}
        <button
          type="button"
          onClick={() => { setMensagens([]); setErro(""); onSessionId?.(null); }}
          title="Começar uma conversa nova com o supervisor"
          className="ml-auto rounded bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-slate-700"
        >
          Nova
        </button>
      </div>

      <div ref={painel} aria-label="Conversa com o supervisor" className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {mensagens.length === 0 && (
          <p className="text-xs text-slate-500">
            O supervisor planeja o trabalho: fatia a task, localiza os arquivos e diz o que cada
            passo precisa fazer. Ele não edita nada. Quando a resposta trouxer o plano, use
            “Aprovar plano” e acompanhe a execução na aba Execução.
          </p>
        )}
        {mensagens.filter((m) => m.role !== "system").map((m, i) => (
          <div key={i} className={m.role === "user" ? "ml-6 text-right" : "mr-6"}>
            <span className="text-[10px] text-slate-500">{m.role === "user" ? "você" : "supervisor"}</span>
            <div className={`mt-1 whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
              m.error ? "bg-red-950/60 text-red-200" : m.role === "user" ? "bg-sky-900/60 text-slate-100" : "bg-slate-800 text-slate-200"
            }`}>
              {m.content}
            </div>
            {m.role === "assistant" && onAprovarPlano && (() => {
              const plano = planoDoTexto(m.content);
              return plano ? <PlanoNaResposta plano={plano} onAprovar={onAprovarPlano} /> : null;
            })()}
          </div>
        ))}
        {carregando && <p className="text-xs text-slate-500">supervisor pensando…</p>}
        {erro && <p role="alert" className="text-xs text-red-400">{erro}</p>}
      </div>

      <form onSubmit={submeter} className="shrink-0 border-t border-slate-800 p-2">
        <textarea
          value={entrada}
          onChange={(e) => setEntrada(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submeter(e); }
          }}
          placeholder="Pedir o plano ao supervisor…"
          rows={2}
          className="w-full resize-none rounded bg-slate-900 px-2 py-1 text-sm text-slate-100"
        />
        <button
          type="submit"
          disabled={carregando || !modelo || !entrada.trim()}
          className="mt-1 rounded bg-violet-700 px-3 py-1 text-xs text-white disabled:opacity-50"
        >
          Enviar
        </button>
      </form>
    </div>
  );
}
