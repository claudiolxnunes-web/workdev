"""Deduplicação e memória entre execuções.

O Supervisor não pode repetir indefinidamente o mesmo alerta. A identidade de
um achado é o `fingerprint` (check + entidade + faixa da condição); a
identidade da *coisa observada* é a `chave_entidade` (sem a faixa). É a
existência das duas que permite distinguir três situações que, olhadas só
pelo fingerprint, seriam indistinguíveis:

  - o mesmo problema, um dia mais velho        → persistente (silencioso)
  - o mesmo problema, agora num patamar pior   → agravado (reportado)
  - um problema novo na mesma entidade         → novo (reportado)

Duas regras de segurança governam a resolução automática:

  1. Só um check que **rodou** nesta execução pode resolver os próprios
     achados. Rodar com `--check X` não pode marcar os achados de Y como
     resolvidos.
  2. Só um check que rodou **com sucesso** pode resolver. Se um check falhar,
     seus achados ficam intactos: senão uma falha transitória marcaria tudo
     como resolvido, e no dia seguinte tudo voltaria como novo — exatamente o
     ruído que a deduplicação existe para evitar.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import config
from .modelo import PESO_SEVERIDADE, Achado, Fato, como_utc, dias_desde


@dataclass
class Reconciliacao:
    """Resultado de comparar os fatos desta execução com o estado anterior."""

    achados: list[Achado] = field(default_factory=list)
    estado_recuperado: bool = False
    semeado: bool = False
    purgados: int = 0

    def por_status(self, status: str) -> list[Achado]:
        return [a for a in self.achados if a.status == status]

    @property
    def contagens(self) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for achado in self.achados:
            contagem[achado.status] = contagem.get(achado.status, 0) + 1
        return contagem

    @property
    def reportaveis(self) -> list[Achado]:
        return [a for a in self.achados if a.reportavel]


class Estado:
    """Mapa fingerprint → registro, persistido em JSON."""

    def __init__(self, diretorio: Path | None = None) -> None:
        self.diretorio = Path(diretorio) if diretorio else config.ESTADO_DIR
        self.arquivo = self.diretorio / "state.json"
        self.arquivo_execucoes = self.diretorio / "runs.jsonl"
        self.registros: dict[str, dict[str, Any]] = {}
        self.recuperado = False

    # ---------------------------------------------------------------- leitura

    def carregar(self) -> "Estado":
        """Lê o estado. Qualquer problema recomeça vazio, sem derrubar a execução.

        Um state.json corrompido é um contratempo; abortar por causa dele
        seria transformar o mecanismo anti-ruído em ponto único de falha.
        """
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("raiz não é objeto")
            if dados.get("versao") != config.VERSAO_ESTADO:
                raise ValueError(f"versão inesperada: {dados.get('versao')!r}")
            registros = dados.get("achados")
            if not isinstance(registros, dict):
                raise ValueError("campo 'achados' ausente ou inválido")
            self.registros = {
                fp: reg for fp, reg in registros.items() if isinstance(reg, dict)
            }
        except FileNotFoundError:
            self.registros = {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.registros = {}
            self.recuperado = True
        return self

    # ------------------------------------------------------------ escrita

    def salvar(self, agora: datetime) -> None:
        """Escrita atômica: tmp no mesmo diretório + replace."""
        self.diretorio.mkdir(parents=True, exist_ok=True)
        carga = {
            "versao": config.VERSAO_ESTADO,
            "atualizado_em": agora.isoformat(),
            "achados": self.registros,
        }
        with tempfile.NamedTemporaryFile(
            "w", dir=self.diretorio, delete=False, encoding="utf-8"
        ) as arquivo:
            json.dump(carga, arquivo, ensure_ascii=False, indent=2, default=str)
            arquivo.write("\n")
            temporario = Path(arquivo.name)
        temporario.chmod(0o644)
        temporario.replace(self.arquivo)

    def registrar_execucao(self, metricas: dict[str, Any]) -> None:
        """Uma linha JSON por execução, em append."""
        self.diretorio.mkdir(parents=True, exist_ok=True)
        with self.arquivo_execucoes.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(metricas, ensure_ascii=False, default=str) + "\n")

    def rotacionar_execucoes(
        self, agora: datetime, dias: int | None = None
    ) -> tuple[int, int]:
        """Descarta execuções mais velhas que a janela. Devolve (removidas, inválidas).

        Roda **antes** de gravar a linha da execução atual, para que ela
        registre a própria limpeza que provocou.

        Escrita atômica (tmp no mesmo diretório + replace) e restrita a
        runs.jsonl: `state.json` nunca é tocado aqui.

        Linha ilegível é **preservada e contada**, não apagada. Sem
        `started_at` não há como saber a idade dela, e apagar dado que não se
        consegue datar seria decidir por conta própria; a contagem no log
        torna o problema visível se o arquivo começar a acumular lixo.
        """
        limite = dias if dias is not None else config.RETENCAO_EXECUCOES_DIAS
        try:
            bruto = self.arquivo_execucoes.read_text(encoding="utf-8")
        except FileNotFoundError:
            return 0, 0
        except (OSError, UnicodeDecodeError):
            return 0, 0

        corte = como_utc(agora) - timedelta(days=limite)
        mantidas: list[str] = []
        removidas = 0
        invalidas = 0

        for linha in bruto.splitlines():
            if not linha.strip():
                continue
            try:
                inicio = como_utc(
                    datetime.fromisoformat(json.loads(linha)["started_at"])
                )
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                invalidas += 1
                mantidas.append(linha)
                continue
            if inicio is None or inicio >= corte:
                mantidas.append(linha)
            else:
                removidas += 1

        if removidas == 0:
            return 0, invalidas

        with tempfile.NamedTemporaryFile(
            "w", dir=self.diretorio, delete=False, encoding="utf-8"
        ) as arquivo:
            for linha in mantidas:
                arquivo.write(linha + "\n")
            temporario = Path(arquivo.name)
        temporario.chmod(0o644)
        temporario.replace(self.arquivo_execucoes)
        return removidas, invalidas

    # ------------------------------------------------------- reconciliação

    def reconciliar(
        self,
        fatos: Iterable[Fato],
        agora: datetime,
        checks_confiaveis: Sequence[str],
        semear: bool = False,
    ) -> Reconciliacao:
        agora_iso = agora.isoformat()
        resultado = Reconciliacao(estado_recuperado=self.recuperado, semeado=semear)
        confiaveis = set(checks_confiaveis)

        vistos_fingerprint: set[str] = set()
        vistos_entidade: set[str] = set()

        for fato in fatos:
            fingerprint = fato.fingerprint
            vistos_fingerprint.add(fingerprint)
            vistos_entidade.add(fato.chave_entidade)

            if semear:
                # Semeadura: tudo entra como já conhecido e nada é reportado.
                # Sem isso, o dia 1 despeja a base inteira de uma vez.
                self.registros[fingerprint] = self._novo_registro(
                    fato, agora_iso, status="persistente"
                )
                resultado.achados.append(
                    self._achado(fato, self.registros[fingerprint], "persistente")
                )
                continue

            anterior = self.registros.get(fingerprint)
            if anterior is not None and anterior.get("status") != "resolvido":
                registro, status = self._atualizar_mesma_faixa(anterior, fato, agora, agora_iso)
            else:
                registro, status = self._transicao_ou_novo(
                    fato, fingerprint, agora_iso
                )

            self.registros[fingerprint] = registro
            resultado.achados.append(self._achado(fato, registro, status))

        resultado.purgados = self._resolver_ausentes(
            resultado, vistos_fingerprint, vistos_entidade, confiaveis, agora, agora_iso, semear
        )
        return resultado

    # ------------------------------------------------------------- internos

    def _novo_registro(
        self, fato: Fato, agora_iso: str, status: str = "novo"
    ) -> dict[str, Any]:
        return {
            "fingerprint": fato.fingerprint,
            "chave_entidade": fato.chave_entidade,
            "check": fato.check,
            "subcheck": fato.subcheck,
            "entity_type": fato.entity_type,
            "entity_id": fato.entity_id,
            "project_id": fato.project_id,
            "project_name": fato.project_name,
            "severity": fato.severity,
            "bucket": fato.bucket,
            "bucket_ordem": fato.bucket_ordem,
            "titulo": fato.titulo,
            "status": status,
            "first_seen_at": agora_iso,
            "last_seen_at": agora_iso,
            "ocorrencias": 1,
            "ultimo_reforco_em": agora_iso,
            "resolvido_em": None,
            "bucket_anterior": None,
            "severidade_anterior": None,
        }

    def _atualizar_mesma_faixa(
        self, anterior: dict[str, Any], fato: Fato, agora: datetime, agora_iso: str
    ) -> tuple[dict[str, Any], str]:
        """Mesmo fingerprint: só a severidade ou o tempo podem ter mudado."""
        registro = dict(anterior)
        severidade_anterior = registro.get("severity")
        piorou = PESO_SEVERIDADE[fato.severity] < PESO_SEVERIDADE.get(
            severidade_anterior, len(PESO_SEVERIDADE)
        )

        if piorou:
            status = "agravado"
            registro["severidade_anterior"] = severidade_anterior
            registro["ultimo_reforco_em"] = agora_iso
        elif self._precisa_reforco(registro, fato, agora):
            status = "reforco"
            registro["ultimo_reforco_em"] = agora_iso
        else:
            status = "persistente"

        registro.update(
            {
                "severity": fato.severity,
                "titulo": fato.titulo,
                "project_name": fato.project_name,
                "last_seen_at": agora_iso,
                "ocorrencias": int(registro.get("ocorrencias", 0)) + 1,
                "status": status,
                "resolvido_em": None,
            }
        )
        return registro, status

    def _transicao_ou_novo(
        self, fato: Fato, fingerprint: str, agora_iso: str
    ) -> tuple[dict[str, Any], str]:
        """Fingerprint inédito: pode ser mudança de faixa ou achado novo."""
        anterior_fp = self._procurar_por_entidade(fato.chave_entidade, exceto=fingerprint)
        if anterior_fp is None:
            return self._novo_registro(fato, agora_iso), "novo"

        velho = self.registros.pop(anterior_fp)
        ordem_antiga = int(velho.get("bucket_ordem", 0))
        if fato.bucket_ordem > ordem_antiga:
            status = "agravado"
        elif fato.bucket_ordem < ordem_antiga:
            status = "melhorou"
        else:
            status = "persistente"

        registro = self._novo_registro(fato, agora_iso, status=status)
        # A entidade continua a mesma: a história dela é preservada.
        registro["first_seen_at"] = velho.get("first_seen_at", agora_iso)
        registro["ocorrencias"] = int(velho.get("ocorrencias", 0)) + 1
        registro["ultimo_reforco_em"] = agora_iso
        registro["bucket_anterior"] = velho.get("bucket")
        registro["severidade_anterior"] = (
            velho.get("severity") if velho.get("severity") != fato.severity else None
        )
        return registro, status

    def _procurar_por_entidade(self, chave: str, exceto: str) -> str | None:
        for fingerprint, registro in self.registros.items():
            if fingerprint == exceto:
                continue
            if registro.get("status") == "resolvido":
                continue
            if registro.get("chave_entidade") == chave:
                return fingerprint
        return None

    def _precisa_reforco(self, registro: dict[str, Any], fato: Fato, agora: datetime) -> bool:
        if fato.severity not in config.SEVERIDADES_COM_REFORCO:
            return False
        ultimo = registro.get("ultimo_reforco_em") or registro.get("first_seen_at")
        if not ultimo:
            return True
        try:
            dias = dias_desde(datetime.fromisoformat(ultimo), agora)
        except (TypeError, ValueError):
            return True
        return dias is not None and dias >= config.REFORCO_DIAS

    def _resolver_ausentes(
        self,
        resultado: Reconciliacao,
        vistos_fingerprint: set[str],
        vistos_entidade: set[str],
        confiaveis: set[str],
        agora: datetime,
        agora_iso: str,
        semear: bool,
    ) -> int:
        purgados = 0
        for fingerprint, registro in list(self.registros.items()):
            if fingerprint in vistos_fingerprint:
                continue

            if registro.get("status") == "resolvido":
                if self._expirou(registro, agora):
                    del self.registros[fingerprint]
                    purgados += 1
                continue

            # Regras de segurança: só resolve quem rodou, e rodou bem.
            if registro.get("check") not in confiaveis:
                continue
            # A entidade apareceu em outra faixa: foi transição, não resolução.
            if registro.get("chave_entidade") in vistos_entidade:
                continue

            registro["status"] = "resolvido"
            registro["resolvido_em"] = agora_iso
            registro["last_seen_at"] = registro.get("last_seen_at", agora_iso)
            if not semear:
                resultado.achados.append(self._achado_de_registro(registro, "resolvido"))
        return purgados

    def _expirou(self, registro: dict[str, Any], agora: datetime) -> bool:
        resolvido_em = registro.get("resolvido_em")
        if not resolvido_em:
            return True
        try:
            dias = dias_desde(datetime.fromisoformat(resolvido_em), agora)
        except (TypeError, ValueError):
            return True
        return dias is not None and dias >= config.RESOLVIDO_TTL_DIAS

    def _achado(self, fato: Fato, registro: dict[str, Any], status: str) -> Achado:
        return Achado(
            fingerprint=fato.fingerprint,
            check=fato.check,
            subcheck=fato.subcheck,
            entity_type=fato.entity_type,
            entity_id=fato.entity_id,
            project_id=fato.project_id,
            project_name=fato.project_name,
            severity=fato.severity,
            bucket=fato.bucket,
            titulo=fato.titulo,
            status=status,
            first_seen_at=registro["first_seen_at"],
            last_seen_at=registro["last_seen_at"],
            ocorrencias=int(registro["ocorrencias"]),
            medidas=dict(fato.medidas),
            evidencia=tuple(fato.evidencia),
            bucket_anterior=registro.get("bucket_anterior"),
            severidade_anterior=registro.get("severidade_anterior"),
        )

    def _achado_de_registro(self, registro: dict[str, Any], status: str) -> Achado:
        """Achado sem Fato: o problema sumiu, só resta o que estava guardado."""
        return Achado(
            fingerprint=registro.get("fingerprint", ""),
            check=registro.get("check", ""),
            subcheck=registro.get("subcheck"),
            entity_type=registro.get("entity_type", ""),
            entity_id=registro.get("entity_id", ""),
            project_id=registro.get("project_id"),
            project_name=registro.get("project_name"),
            severity=registro.get("severity", "info"),
            bucket=registro.get("bucket", ""),
            titulo=registro.get("titulo", ""),
            status=status,
            first_seen_at=registro.get("first_seen_at", ""),
            last_seen_at=registro.get("last_seen_at", ""),
            ocorrencias=int(registro.get("ocorrencias", 0)),
        )
