"""WorkDev Supervisor — camada de observação somente leitura.

Nível de autonomia 0: lê, correlaciona e recomenda. Nunca escreve no Postgres
do WorkDev, no RAG, no backlog, no git, no systemd ou nos agentes.

Comando operacional (único suportado):

    cd /opt/workdev
    apps/api/venv/bin/python -m scripts.supervisor --once

O Supervisor roda **no venv da API** (`/opt/workdev/apps/api/venv`), que já traz
psycopg, python-dotenv, anthropic e pytest. Nada dele é instalado globalmente:
não há `pip install` de psycopg ou pytest no Python do sistema, e não há venv
próprio a manter.

O `-m scripts.supervisor` depende do cwd ser `/opt/workdev` (o pacote é
resolvido como namespace package a partir da raiz do repositório). Quem rodar
por systemd precisa de `WorkingDirectory=/opt/workdev`.

Plano de referência: docs/supervisor-mvp-plano.md
"""

__all__ = ["config", "modelo", "redacao", "estado"]
