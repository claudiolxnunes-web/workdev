"""Check: divergência entre o código considerado pronto e o que está no ar.

Não é CI/CD. São sete leituras baratas de estado, todas somente leitura.

Decisão explícita: **o Supervisor não invoca `verificar-deploy.sh`.** Aquele
script roda `pnpm build`, que escreve em `dist/` e leva minutos — violaria
tanto o Nível 0 quanto o orçamento de tempo. Aqui só os sinais read-only dele
(árvore suja, órfão na porta) são reimplementados. Dívida registrada: a longo
prazo, extrair o subconjunto comum para um módulo lido pelos dois.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..contexto import Contexto
from ..modelo import Fato, classificar, dias_desde
from ..readers import sistema


NOME = "deploy_drift"
ENTIDADE = "workdev"


def coletar(contexto: Contexto) -> list[Fato]:
    repo = contexto.repo()
    agora = contexto.agora
    fatos: list[Fato] = []

    fatos += _codigo_nao_commitado(repo, agora)
    fatos += _commits_nao_enviados(repo, agora)
    fatos += _producao_atras_do_trabalho(repo, agora)
    fatos += _build_desatualizado(repo, agora)
    fatos += _servico_mais_velho_que_o_codigo(repo, agora)
    fatos += _migration_pendente(contexto, repo, agora)
    fatos += _porta_disputada(agora)
    return fatos


def _fato(
    subcheck: str,
    severidade: str,
    bucket: str,
    bucket_ordem: int,
    titulo: str,
    agora: datetime,
    medidas: dict,
    evidencia: tuple[str, ...],
) -> Fato:
    return Fato(
        check=NOME,
        subcheck=subcheck,
        entity_type="repositorio",
        entity_id=ENTIDADE,
        project_name="WorkDev Core",
        severity=severidade,
        bucket=bucket,
        bucket_ordem=bucket_ordem,
        titulo=titulo,
        detected_at=agora.isoformat(),
        medidas=medidas,
        evidencia=evidencia,
    )


def _codigo_nao_commitado(repo, agora: datetime) -> list[Fato]:
    arquivos = repo.modificados_rastreados()
    if not arquivos:
        return []
    bucket, ordem = classificar(len(arquivos), config.FAIXAS_CONTAGEM)
    return [
        _fato(
            "uncommitted_in_production",
            "high",
            bucket,
            ordem,
            f"{len(arquivos)} arquivo(s) rastreado(s) modificado(s) — "
            "deploy.sh builda a árvore de trabalho, então isso já está em produção",
            agora,
            {"arquivos": arquivos[:20], "total": len(arquivos)},
            ("git -C /opt/workdev status --porcelain",),
        )
    ]


def _commits_nao_enviados(repo, agora: datetime) -> list[Fato]:
    intervalo = f"{config.REMOTO}/{config.BRANCH_TRABALHO}..{config.BRANCH_TRABALHO}"
    if not repo.referencia_existe(f"{config.REMOTO}/{config.BRANCH_TRABALHO}"):
        return []
    quantidade = repo.contar_commits(intervalo)
    if not quantidade:
        return []

    mais_antigo = repo.data_commit_mais_antigo(intervalo)
    dias = dias_desde(mais_antigo, agora)
    if dias is None or dias < config.COMMITS_NAO_ENVIADOS_DIAS:
        return []  # commitar e empurrar no mesmo dia é fluxo normal

    bucket, ordem = classificar(quantidade, config.FAIXAS_CONTAGEM)
    return [
        _fato(
            "unpushed_commits",
            "high",
            bucket,
            ordem,
            f"{quantidade} commit(s) em {config.BRANCH_TRABALHO} existem só nesta VPS "
            f"há {dias} dias",
            agora,
            {"commits": quantidade, "dias": dias, "intervalo": intervalo},
            (
                f"git -C /opt/workdev log --oneline {intervalo}",
                "# medido contra o ultimo fetch local: o Supervisor nao faz fetch",
            ),
        )
    ]


def _producao_atras_do_trabalho(repo, agora: datetime) -> list[Fato]:
    intervalo = f"{config.BRANCH_PRODUCAO}..{config.BRANCH_TRABALHO}"
    if not (
        repo.referencia_existe(config.BRANCH_PRODUCAO)
        and repo.referencia_existe(config.BRANCH_TRABALHO)
    ):
        return []
    quantidade = repo.contar_commits(intervalo)
    if not quantidade:
        return []
    bucket, ordem = classificar(quantidade, config.FAIXAS_CONTAGEM)
    return [
        _fato(
            "main_behind",
            "medium",
            bucket,
            ordem,
            f"{config.BRANCH_PRODUCAO} está {quantidade} commit(s) atrás de "
            f"{config.BRANCH_TRABALHO}",
            agora,
            {"commits": quantidade, "intervalo": intervalo},
            (f"git -C /opt/workdev log --oneline {intervalo}",),
        )
    ]


def _build_desatualizado(repo, agora: datetime) -> list[Fato]:
    build = repo.mtime(config.CAMINHO_BUILD)
    if build is None:
        return []
    fonte, arquivo = repo.mtime_mais_recente(config.FONTES_FRONTEND)
    if fonte is None or fonte <= build:
        return []
    horas = round((fonte - build).total_seconds() / 3600, 1)
    dias = max(dias_desde(build, agora) or 0, 0)
    bucket, ordem = classificar(dias, config.FAIXAS_IDADE_PLANO)
    return [
        _fato(
            "stale_build",
            "high",
            bucket,
            ordem,
            f"fonte do frontend mais novo que o build ({horas}h de diferença): {arquivo}",
            agora,
            {
                "arquivo": arquivo,
                "build_em": build.isoformat(),
                "fonte_em": fonte.isoformat(),
                "horas_de_diferenca": horas,
            },
            (
                f"ls -l /opt/workdev/{config.CAMINHO_BUILD}",
                f"find /opt/workdev/{config.FONTES_FRONTEND} -newer "
                f"/opt/workdev/{config.CAMINHO_BUILD}",
            ),
        )
    ]


def _servico_mais_velho_que_o_codigo(repo, agora: datetime) -> list[Fato]:
    propriedades = sistema.propriedades_unit(config.UNIT_API)
    if not propriedades or propriedades.get("ActiveState") != "active":
        return []
    desde = sistema.ativo_desde(propriedades)
    if desde is None:
        return []
    fonte, arquivo = repo.mtime_mais_recente(config.FONTES_BACKEND, sufixos=(".py",))
    if fonte is None or fonte <= desde:
        return []
    horas = round((fonte - desde).total_seconds() / 3600, 1)
    dias = max(dias_desde(desde, agora) or 0, 0)
    bucket, ordem = classificar(dias, config.FAIXAS_IDADE_PLANO)
    return [
        _fato(
            "service_older_than_code",
            "high",
            bucket,
            ordem,
            f"{config.UNIT_API} está no ar desde antes da última alteração do backend "
            f"({horas}h): {arquivo}",
            agora,
            {
                "arquivo": arquivo,
                "ativo_desde": desde.isoformat(),
                "fonte_em": fonte.isoformat(),
                "nrestarts": propriedades.get("NRestarts"),
            },
            (
                f"systemctl show {config.UNIT_API} -p ActiveEnterTimestamp -p NRestarts",
                f"ls -l /opt/workdev/{arquivo}",
            ),
        )
    ]


def _migration_pendente(contexto, repo, agora: datetime) -> list[Fato]:
    """Compara alembic_version (banco) com o head do diretório (disco).

    Não usa /api/system/migrations de propósito: a rota exige autenticação, e
    um GET sem credencial devolve 401 — o check falharia em silêncio, que é a
    classe de defeito que o Supervisor existe para encontrar. Lendo banco e
    disco, ele também continua funcionando com a API fora do ar.
    """
    linhas = contexto.workdev.consultar("SELECT version_num FROM alembic_version")
    if not linhas:
        return []
    atual = linhas[0]["version_num"]
    _, heads = repo.revisoes_alembic(config.DIRETORIO_MIGRATIONS)
    if not heads:
        return []

    if len(heads) > 1:
        return [
            _fato(
                "migration_multiplos_heads",
                "critical",
                "conflito",
                0,
                f"{len(heads)} heads no diretório de migrations — histórico bifurcado",
                agora,
                {"heads": sorted(heads), "atual": atual},
                ("apps/api/venv/bin/alembic heads",),
            )
        ]

    head = next(iter(heads))
    if atual == head:
        return []
    return [
        _fato(
            "migration_pending",
            "high",
            "pendente",
            0,
            f"migration pendente: banco em {atual}, código em {head}",
            agora,
            {"current": atual, "head": head},
            (
                "SELECT version_num FROM alembic_version;",
                "apps/api/venv/bin/alembic current",
            ),
        )
    ]


def _porta_disputada(agora: datetime) -> list[Fato]:
    quantidade = sistema.processos_na_porta(config.PORTA_API)
    if quantidade is None or quantidade <= 1:
        return []
    return [
        _fato(
            "port_conflict",
            "critical",
            "conflito",
            0,
            f"{quantidade} processos ouvindo na porta {config.PORTA_API} — "
            "padrão do uvicorn órfão fora do systemd",
            agora,
            {"processos": quantidade, "porta": config.PORTA_API},
            (f"ss -tlnp | grep :{config.PORTA_API}",),
        )
    ]
