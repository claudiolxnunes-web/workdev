# ADR 007 — BUILD na sessão persistente local-code

Status: proposed (implementação submetida a revisão independente).
Registro API: `9ca52f5b-115f-4eb8-95e8-439773f11d8c`.
Plano aprovado: 79c20440-bea0-42dc-88dd-87f7d78145b4 v1.
Run: 0cfdaf23-51f3-41fa-aeb7-69a2537b7365.

## Decisão

O lifecycle continua sendo o owner físico de `local-code`. A fila existente
AgentBuildJob pertence ao backend; build_worker é o único despachante. Para
local-code ele não chama HTTP nem aplica envelopes. Outros runtimes mantêm o
ADR 005. TerminalSession e WebSocket são acessos ao tmux canônico, sem outro
Qwen ou sessão `auto-local-code-*`.

A extensão do lifecycle usa registro durável de protocolo, locks de arquivo e
binding com modo `persistent_cli`, além de PID/starttime e run_id. Isso não é
outro manager de PTY. Jobs permanecem queued enquanto o canal está ocupado,
sem hooks ou offline. Abrir o terminal não inicia processos de agente.

Entrega tem intenção persistida, nonce, hash do contexto e confirmação pelo
hook UserPromptSubmit da CLI. O transporte é o watcher nativo JSONL da
própria TUI Qwen 0.24.0; ele só submete quando a CLI está ociosa. O
hook fornece o plano persistido como contexto e recusa marcador divergente ou
duplicado. Crash entre envio e confirmação não provoca replay automático.
Eventos de Run registram intenção, sessão, identidade, hash e confirmação.

O hook Stop inicia uma barreira WORKDEV_IDLE pelo watcher. Somente o
UserPromptSubmit dessa barreira confirma o fim do turno; isso não conclui a task. Os gates e a revisão
continuam no workflow existente. Uma run ocupa a sessão até sua liberação
confirmada; não basta uma mudança de status no banco para inferir inatividade.
Trabalho manual na CLI ocupa o mesmo canal e impede entrega de outra run.

Parar Run cancela a entrega ainda não enviada ou pede interrupção do turno
vinculado e espera confirmação da CLI, preservando Qwen/tmux/modelo. Sem
confirmação, retorna erro e mantém a reserva. Parar agente continua no lifecycle
e recusa execução ativa. Uma sessão substituída nunca recebe teclas por um
vínculo antigo. Browser disconnect fecha apenas o attach.

## Alternativas

- Reutilizar `bind_run` sem modo distinto: rejeitada, pois exige sessão exclusiva
  e sua parada mata o tmux, contrariando o plano.
- `send-keys` sem protocolo: rejeitada, não confirma recebimento, não impede
  duplicação depois de crash nem prova cancelamento.
- Novo manager PTY ou novo Qwen headless: rejeitada, cria outra autoridade ou
  outro executor, diferente do terminal exigido.
- Adaptar lifecycle/fila existentes com handshake da CLI: escolhida; exige
  testes reais dos hooks e implantação controlada no launcher.

## Implantação e limites

Uma CLI já aberta sem hooks não pode ser adotada como IDLE por heurística.
Fica indisponível para despacho até ser iniciada com o launcher atualizado,
após o trabalho manual terminar. Não reiniciar nem matar essa sessão no deploy.
O registro do protocolo não contém credenciais de API. A configuração de hooks
é sobreposta à configuração local sem mudar catálogo de modelos/providers.
Os testes usam tmux e Qwen reais em socket/diretório isolados e endpoint de
inferência de teste; isso não mede qualidade do Qwen 27B nem inicia o llama real.

## Validação

Evidências e limitações em `../planning/local-code-validation.md`. Revisão
independente solicitada ao Gemini; o executor não registra veredito.

## Falhas e recuperação conservadora

Timeout de recebimento conserva intenção e reserva: timeout não prova ausência
de execução. O reconciliador recupera acknowledgements tardios sem replay.
Parar Run invalida a entrega pendente antes de solicitar a barreira nativa.
Nunca devolver automaticamente para queued por falta de ack.

Após crash, nova identidade não adota a run antiga. Parar Run pode cancelar a
reserva antiga se `/proc` comprovar término/reuso de PID e não houver ferramentas
ou trabalho background registrados. Somente depois do commit o reconciliador
libera a substituta registrada por seu próprio hook. Com ferramentas pendentes,
a quarentena é deliberada: filhos podem sobreviver ao Qwen. Exige inspeção
operacional dos processos residuais, sem inferir que morreram com o pai.

Uma CLI antiga sem hooks permanece utilizável manualmente, mas não recebe runs
até ser iniciada pelo launcher atualizado. O serviço do worker deve estar em
execução para consumir a fila; a flag de envelopes HTTP não desativa esse canal.
Arquivos privados em `/tmp/workdev-local-code-settings-*` têm lifetime da CLI;
a limpeza deve ocorrer após a saída, nunca durante uma sessão ativa.
