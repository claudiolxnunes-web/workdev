"""WorkDev Supervisor — camada de observação somente leitura.

Nível de autonomia 0: lê, correlaciona e recomenda. Nunca escreve no Postgres
do WorkDev, no RAG, no backlog, no git, no systemd ou nos agentes.

Uso:
    PYTHONPATH=/opt/workdev/scripts \\
      /opt/workdev/apps/api/venv/bin/python -m supervisor --once

Plano de referência: docs/supervisor-mvp-plano.md
"""

__all__ = ["config", "modelo", "redacao"]
