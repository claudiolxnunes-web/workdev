# Deploy Canônico do WorkDev

Fonte canônica para TODOS os agentes.

## Regra

NUNCA improvisar o processo de deploy.
NUNCA executar `deploy.sh` sem `proof_id`.
NUNCA gerar prova manualmente com `deploy_proof.py`.
NUNCA redescobrir o fluxo procurando scripts, salvo se este runbook estiver comprovadamente desatualizado.

## Fluxo oficial

### 1. Prepare

```bash
cd /opt/workdev
workdev-deployctl prepare
