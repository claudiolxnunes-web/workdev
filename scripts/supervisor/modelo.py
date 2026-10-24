"""Estruturas de dados do Supervisor.

Invariante central do MVP: tudo nesta camada é determinístico. Nenhum campo
de Fato é produzido, alterado ou reordenado por LLM — o modelo entra depois,
recebe Fatos prontos e devolve apenas prioridade e prosa.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence


SEVERIDADES = ("critical", "high", "medium", "info")
PESO_SEVERIDADE = {nome: peso for peso, nome in enumerate(SEVERIDADES)}


def agora_utc() -> datetime:
    """Instante atual, sempre com fuso explícito."""
    return datetime.now(timezone.utc)


def como_utc(valor: datetime | None) -> datetime | None:
    """Garante fuso UTC em um datetime vindo do banco.

    Armadilha de schema real: backlog.created_at/updated_at são
    `timestamp without time zone`, enquanto execution_plans e agent_runs usam
    `timestamptz`. O servidor roda em UTC (verificado), então o valor naive
    já está em UTC — mas depender disso implicitamente quebra no dia em que
    alguém mudar o fuso do container. Aqui a suposição fica explícita.
    """
    if valor is None:
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)


def dias_desde(momento: datetime | None, agora: datetime) -> int | None:
    """Idade em dias inteiros, truncada. None se o momento não existir."""
    momento = como_utc(momento)
    if momento is None:
        return None
    return (como_utc(agora) - momento).days


_PREFIXO_ADR = re.compile(r"^adr[\s\-—:]*\d*[\s\-—:]*", re.IGNORECASE)


def normalizar_titulo(texto: str | None) -> str:
    """Reduz um título à forma comparável entre stores diferentes.

    O mesmo ADR aparece como linha em `knowledge`, como linha em `adrs` e
    como arquivo em `decisions/` — com numeração, travessão e acentuação
    divergentes. A comparação é exata sobre esta forma normalizada: nada de
    similaridade difusa, que não seria determinística o bastante para virar
    fingerprint.
    """
    if not texto:
        return ""
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    limpo = _PREFIXO_ADR.sub("", sem_acento.strip().lower())
    return " ".join(limpo.replace("—", " ").replace("-", " ").split())


def classificar(valor: int, faixas: Sequence[tuple[int | None, str]]) -> tuple[str, int]:
    """Devolve (rótulo da faixa, ordem da faixa).

    O rótulo é o que entra no fingerprint: é ele que distingue "envelheceu um
    dia" (mesmo achado) de "piorou de patamar" (achado agravado). A ordem é o
    que permite dizer, na reconciliação, se a mudança de faixa foi para pior
    ou para melhor — o rótulo sozinho não é comparável.
    """
    for indice, (limite, rotulo) in enumerate(faixas):
        if limite is None or valor < limite:
            return rotulo, indice
    return faixas[-1][1], len(faixas) - 1


def faixa(valor: int, faixas: Sequence[tuple[int | None, str]]) -> str:
    """Só o rótulo da faixa."""
    return classificar(valor, faixas)[0]


@dataclass(frozen=True)
class Fato:
    """Uma observação determinística sobre o estado real do WorkDev."""

    check: str
    entity_type: str
    entity_id: str
    severity: str
    bucket: str
    titulo: str
    detected_at: str
    subcheck: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    medidas: dict[str, Any] = field(default_factory=dict)
    evidencia: tuple[str, ...] = ()
    bucket_ordem: int = 0

    def __post_init__(self) -> None:
        if self.severity not in PESO_SEVERIDADE:
            raise ValueError(f"severidade desconhecida: {self.severity!r}")

    @property
    def fingerprint(self) -> str:
        """Identidade estável do achado: check + entidade + faixa da condição."""
        base = "|".join(
            (self.check, self.subcheck or "", self.entity_id, self.bucket)
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

    @property
    def chave_entidade(self) -> str:
        """Identidade da coisa observada, independente da faixa.

        É o que liga duas execuções em que o mesmo problema mudou de patamar:
        o fingerprint muda (o bucket faz parte dele), a chave de entidade não.
        """
        return "|".join((self.check, self.subcheck or "", self.entity_id))

    @property
    def peso(self) -> int:
        return PESO_SEVERIDADE[self.severity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "check": self.check,
            "subcheck": self.subcheck,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "severity": self.severity,
            "bucket": self.bucket,
            "bucket_ordem": self.bucket_ordem,
            "titulo": self.titulo,
            "medidas": dict(self.medidas),
            "evidencia": list(self.evidencia),
            "detected_at": self.detected_at,
        }


# Estados possíveis de um achado entre execuções.
STATUS_REPORTAVEIS = ("novo", "agravado", "reforco", "resolvido")
STATUS_SILENCIOSOS = ("persistente", "melhorou")
STATUS = STATUS_REPORTAVEIS + STATUS_SILENCIOSOS


@dataclass
class Achado:
    """Um Fato situado no tempo: o que mudou desde a execução anterior.

    Achado é o que o relatório consome. Os campos vindos do LLM (etapa E4)
    nascem None e nunca sobrescrevem nada de determinístico.
    """

    fingerprint: str
    check: str
    subcheck: str | None
    entity_type: str
    entity_id: str
    project_id: str | None
    project_name: str | None
    severity: str
    bucket: str
    titulo: str
    status: str
    first_seen_at: str
    last_seen_at: str
    ocorrencias: int
    medidas: dict[str, Any] = field(default_factory=dict)
    evidencia: tuple[str, ...] = ()
    bucket_anterior: str | None = None
    severidade_anterior: str | None = None
    prioridade: int | None = None
    impacto: str | None = None
    risco: str | None = None
    recomendacao: str | None = None
    acao_sugerida: str | None = None

    @property
    def peso(self) -> int:
        return PESO_SEVERIDADE[self.severity]

    @property
    def reportavel(self) -> bool:
        return self.status in STATUS_REPORTAVEIS

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "check": self.check,
            "subcheck": self.subcheck,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "severity": self.severity,
            "bucket": self.bucket,
            "titulo": self.titulo,
            "status": self.status,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "ocorrencias": self.ocorrencias,
            "medidas": dict(self.medidas),
            "evidencia": list(self.evidencia),
            "bucket_anterior": self.bucket_anterior,
            "severidade_anterior": self.severidade_anterior,
            "prioridade": self.prioridade,
            "impacto": self.impacto,
            "risco": self.risco,
            "recomendacao": self.recomendacao,
            "acao_sugerida": self.acao_sugerida,
        }


def ordenar_achados(achados: Iterable[Achado]) -> list[Achado]:
    """Ordem determinística do relatório, antes de qualquer LLM.

    Severidade primeiro; dentro dela, o que mudou vem antes do que só
    persiste; por último, o mais antigo.
    """
    peso_status = {nome: peso for peso, nome in enumerate(
        ("agravado", "novo", "reforco", "resolvido", "melhorou", "persistente")
    )}
    return sorted(
        achados,
        key=lambda a: (
            a.peso,
            peso_status.get(a.status, 99),
            -(a.medidas.get("dias_parado") or a.medidas.get("dias") or 0),
            a.check,
            a.entity_id,
        ),
    )


def ordenar(fatos: Iterable[Fato]) -> list[Fato]:
    """Ordem determinística: severidade, depois o mais antigo primeiro."""
    return sorted(
        fatos,
        key=lambda f: (
            f.peso,
            -(f.medidas.get("dias_parado") or f.medidas.get("dias") or 0),
            f.check,
            f.entity_id,
        ),
    )


class LeituraIndisponivel(RuntimeError):
    """Fonte opcional fora do ar: degrada a execução, não a derruba."""
