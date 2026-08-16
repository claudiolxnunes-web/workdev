"""Estruturas de dados do Supervisor.

Invariante central do MVP: tudo nesta camada é determinístico. Nenhum campo
de Fato é produzido, alterado ou reordenado por LLM — o modelo entra depois,
recebe Fatos prontos e devolve apenas prioridade e prosa.
"""

from __future__ import annotations

import hashlib
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


def faixa(valor: int, faixas: Sequence[tuple[int | None, str]]) -> str:
    """Converte um valor contínuo no rótulo da sua faixa.

    O rótulo é o que entra no fingerprint: é ele que distingue "envelheceu um
    dia" (mesmo achado) de "piorou de patamar" (achado agravado).
    """
    for limite, rotulo in faixas:
        if limite is None or valor < limite:
            return rotulo
    return faixas[-1][1]


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
            "titulo": self.titulo,
            "medidas": dict(self.medidas),
            "evidencia": list(self.evidencia),
            "detected_at": self.detected_at,
        }


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
