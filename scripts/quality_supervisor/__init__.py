"""WorkDev Quality Supervisor.

Le issues nao resolvidas no GlitchTip (backend workdev-api e frontend
workdev-web) e avisa no Telegram o que e novo ou piorou. Reaproveita
modelo, redacao, entrega e reconciliacao de estado do
scripts.supervisor -- mesma disciplina, fonte de dados diferente.

Nivel 0: so le e avisa. Nao resolve issue, nao silencia, nao faz deploy.
"""
