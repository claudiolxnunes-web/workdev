# Terminal do Agente Local — configuração e continuação

Atualizado em 01/10/2026. Este documento substitui o retrato inicial que previa o dev 7B como padrão. Não autoriza commit, deploy, migration ou restart.

## Objetivo e modelos

O LLM maior escolhe a tarefa e os trechos reais, revisa a proposta e conduz a aplicação. O modelo local gera propostas, sem aplicar patches, commitar ou implantar. O padrão configurado é `moe` (Qwen3.8 35B A3B MoE); `dev`, `q27` e `fast` são reservas. Um modelo configurado pode estar desligado.

O observer padrão da CLI é `openai/gpt-5.6-luna`, via OpenRouter. O DeepSeek V4 Flash continua como alternativa explícita. Luna teve 7/8 vereditos exatos, 8/8 classificações bom/ruim certas, um falso positivo e zero falhas no comparativo registrado. Isso é uma amostra pequena, não comprova confiabilidade geral. Na rodada posterior o DeepSeek falhou em dois casos; a tabela do comparativo anterior não representa essa rodada.

## Fluxo

1. O orquestrador monta uma tarefa com enunciado, trechos reais, formato esperado e escopo.
2. `rodar` grava a proposta; `--stream` usa um vigia de símbolos e reenvia no máximo uma vez. `ainda_suspeitos` exige revisão mesmo quando a chamada terminou com sucesso.
3. `ferramentas` e `broker` permitem pedidos de leitura: o processo intermediário valida caminhos e lê os trechos. O modelo não recebe acesso direto ao filesystem nem shell.
4. `verificar` usa um commit de base e uma cópia descartável para testar diff, escopo e referências. Passar nessa checagem não comprova todos os requisitos funcionais.
5. `observar` envia enunciado, trechos, proposta e checagens ao Luna e grava parecer, custo e tempo. Não reenvia automaticamente nem aplica a correção.
6. `avaliar` registra a revisão do operador. `resumo` mantém essa avaliação separada da avaliação do observer.

Os artefatos ficam em `tmp/bancada/`: propostas, `_resumo.json`, `verificacoes`, `pareceres` e `registro.jsonl`. A chave da API do WorkDev fica fora das chamadas do modelo; a chave da OpenRouter só é usada pelo observer e não entra no prompt nem nos registros.

## Interface e fase 2

O MVP publicado em `/bancada` mostra estado, propostas, checagens e pareceres, por endpoints autenticados de leitura. A fase 2 prevista inclui pedir parecer, outra opinião, reenvio explícito, streaming e terminal. A existência de código novo no checkout não comprova publicação. Não alterar AgentsPage, handoff.py, catálogo ou migrations para implementar este fluxo.

## Medição de tarefas reais

Piloto preparado em `tmp/bancada/piloto-triagem/tarefas.json` e `corpus.json`: cinco itens reais em estado `todo`, com UUID e título preservados, para resumo em JSON. Mede triagem repetitiva, não geração de patches. A primeira tentativa não executou tarefa alguma porque `127.0.0.1:8080/health` não respondeu. Não registrar taxa de aproveitamento antes de gerar, verificar e revisar as saídas.

As duas propostas MoE anteriores também precisam de avaliação: `pytest_current` e `vigia_teste`. A segunda ainda chama `restart_llama_server`, nome inexistente, após o reenvio. Não tratar sucesso HTTP como proposta aproveitada.

## tmux e timeouts

O tmux dos agentes pertence a `workdev-agents.service`. Um deploy da API não deve recriá-lo. Conferir sessões como usuário `workdev`, usando o socket `/tmp/tmux-999/default`; consultar o tmux de root dá um falso retrato de ausência.

Correção preparada no repositório: lock até 60s, confirmação 1s, cliente de restart limitado a 60s e espera de servidor até 30s; `TimeoutStartSec=180` e timeout da API de 185s. O timeout do cliente systemctl não cancela necessariamente o job já enviado ao systemd. A API converte TimeoutExpired em erro de lifecycle e não repete o restart automaticamente. Validado com 116 testes de lifecycle/tmux e checagem de sintaxe shell. A instalação dos arquivos e o deploy são etapas separadas, ainda sem execução nesta continuação.

## Continuação

- Executar o piloto quando o modelo estiver disponível e autorizado; verificar JSON e confrontar o resumo com cada item original, pedir parecer e registrar a avaliação.
- Medir tempo do modelo e custo do observer; o tempo de revisão do LLM maior também conta para decidir se compensa.
- Instalar e publicar o ajuste de timeout somente após autorização; conferir sessões antes e depois do deploy.
- Revisar a fase 2 contra os resultados do piloto e o trabalho concorrente existente, preservando propostas como propostas.
