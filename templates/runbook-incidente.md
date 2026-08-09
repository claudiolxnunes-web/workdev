# Runbook — [nome do incidente]

- **Serviço:** `<unit systemd>` · **App:** `<nome>` · **VPS:** VPS1 | VPS2
- **Domínio:** `<app>.bpfconsult.com.br` · **Porta interna:** `<porta>`
- **Supabase ref:** `<ref>` · **Repo:** `<url>`
- **Severidade:** crítica (cliente parado) | alta | média | baixa

> Adaptado de `incident-runbook-templates`. As cinco fases são: detecção,
> triagem, mitigação, resolução, comunicação. O que muda no seu caso é que
> **não existe plantão** — solo founder significa que o runbook precisa ser
> executável cansado, às 23h, do celular. Comandos curtos, um por bloco.

## 1. Detecção

Como você fica sabendo:

- [ ] Alerta Telegram do script de backup / heartbeat
- [ ] Cliente avisou
- [ ] Você percebeu

**Confirme antes de agir.** Metade dos incidentes reportados não existe.

```bash
curl -sI https://<domínio> | head -1
```

```bash
systemctl is-active <unit>
```

## 2. Triagem — as 4 perguntas

Responda nesta ordem. A primeira resposta "não" indica onde está o problema.

| # | Pergunta | Comando |
| --- | --- | --- |
| 1 | O serviço está ativo? | `systemctl is-active <unit>` |
| 2 | Está escutando na porta? | `ss -ltnp \| grep :<porta>` |
| 3 | O Traefik alcança? | `curl -sI http://172.18.0.1:<porta> \| head -1` |
| 4 | O domínio responde? | `curl -sI https://<domínio> \| head -3` |

**1 falhou** → app caiu, veja os logs
**1 ok, 2 falhou** → subiu mas não fez bind; erro de config ou porta ocupada
**2 ok, 3 falhou** → roteamento Traefik, não é a aplicação
**3 ok, 4 falhou** → TLS, DNS ou o próprio Traefik

Logs:

```bash
journalctl -u <unit> -n 80 --no-pager
```

## 3. Mitigação — restaurar antes de entender

Cliente parado tem prioridade sobre causa raiz. **Anote o que você observou
antes de mexer** — reinício apaga evidência.

```bash
journalctl -u <unit> -n 200 --no-pager > /tmp/incidente-$(date +%Y%m%d-%H%M).log
```

Só então:

```bash
systemctl restart <unit>
```

Confirme que subiu de verdade — ativo com timestamp velho significa que não
reiniciou:

```bash
systemctl show -p ActiveEnterTimestamp <unit>
```

Se não resolver, o rollback é o commit anterior conhecido bom. **Nunca** edite
código em produção durante incidente.

## 4. Resolução

Rode o gate de deploy completo — as 6 provas. Incidente resolvido é incidente
que passou no gate, não incidente que parou de dar erro.

Se envolveu dados, verifique o backup **antes** de considerar encerrado:

```bash
ls -la /opt/backups/ | tail -5
```

## 5. Comunicação

Cliente afetado: o que aconteceu, o que já está normal, o que você vai fazer pra
não repetir. Sem jargão.

## 6. Pós-incidente

Preencha **no mesmo dia**. Memória de incidente evapora em 48h.

- **Começou:** · **Detectado:** · **Mitigado:** · **Resolvido:**
- **Causa raiz:**
- **Por que a detecção demorou o que demorou:**
- **O que teria evitado:**
- **Ação concreta:** [uma só, com prazo. Cinco ações viram zero ações.]

Se a causa raiz revelou uma decisão de arquitetura, abra um ADR. Se revelou um
procedimento que você vai repetir, vire skill.
