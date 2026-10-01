"""Bancada Local — MVP somente leitura (só GET).

Lê apenas a pasta da Bancada (tmp/bancada/ do checkout, ou WORKDEV_BANCADA_DIR):
propostas <modelo>/<id>.txt, _resumo.json, verificacoes/, pareceres/ e
registro.jsonl. Nada aqui roda modelo, aplica patch, grava arquivo ou reenvia.
Todo caminho é resolvido com realpath e precisa ficar dentro da pasta; as
pastas internas da CLI (_base, _trabalho) nunca são lidas.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/bancada", tags=["bancada"])

PADRAO = "/opt/workdev/tmp/bancada"
NOME_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
PASTAS_INTERNAS = {"verificacoes", "pareceres", "_base", "_trabalho"}
LIMITE_TEXTO = 20000
LLAMA_KEY_FILE = Path("/var/lib/workdev-llama/model")
# Qualquer coisa com cara de chave sai mascarada, por precaução.
CHAVE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|sb_secret_[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._-]{12,})")


def raiz() -> Path:
    return Path(os.path.realpath(os.environ.get("WORKDEV_BANCADA_DIR", PADRAO)))


def _dentro(*partes: str) -> Path:
    for parte in partes:
        if not NOME_VALIDO.match(parte) and not re.match(r"^[A-Za-z0-9_-]{1,80}\.(txt|json)$", parte):
            raise HTTPException(400, "nome inválido")
    base = raiz()
    alvo = Path(os.path.realpath(base.joinpath(*partes)))
    if base not in alvo.parents:
        raise HTTPException(400, "fora da pasta da Bancada")
    if any(p in {"_base", "_trabalho"} for p in alvo.relative_to(base).parts):
        raise HTTPException(400, "pasta interna da CLI")
    return alvo


def _mascarar(valor):
    if isinstance(valor, str):
        return CHAVE.sub("[mascarado]", valor)
    if isinstance(valor, list):
        return [_mascarar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _mascarar(v) for k, v in valor.items()}
    return valor


def _ler_json(caminho: Path) -> dict | None:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else None
    except (OSError, ValueError):
        return None


def _registros() -> list[dict]:
    try:
        linhas = (raiz() / "registro.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    saida = []
    for linha in linhas:
        try:
            dado = json.loads(linha)
        except ValueError:
            continue
        if isinstance(dado, dict) and "id" in dado and "modelo" in dado:
            saida.append(dado)
    return saida


def _modelos() -> list[str]:
    base = raiz()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and NOME_VALIDO.match(p.name) and p.name not in PASTAS_INTERNAS)


def _pareceres(caso: str) -> list[dict]:
    pasta = raiz() / "pareceres"
    if not pasta.is_dir():
        return []
    saida = []
    for arquivo in sorted(pasta.glob(f"{caso}__*.json")):
        dados = _ler_json(arquivo)
        if dados and dados.get("id") == caso:
            parecer = dados.get("parecer") or {}
            saida.append({
                "observer": dados.get("observer"), "ok": dados.get("ok"),
                "veredito": parecer.get("veredito"), "erros": parecer.get("erros") or [],
                "prompt_correcao": parecer.get("prompt_correcao") or "",
                "custo_usd": dados.get("custo_usd"), "segundos": dados.get("segundos"),
                "falhas": dados.get("falhas") or [], "data": dados.get("data")})
    return saida


def _contagem(achados: list[dict]) -> dict:
    return {nivel: sum(a.get("severidade") == nivel for a in achados) for nivel in ("erro", "aviso", "info")}


@router.get("/estado")
def estado():
    """llama-server: ligado, chave, modelo e memória. Sem trocar nada."""
    try:
        ativo = subprocess.run(["systemctl", "is-active", "workdev-llama"], capture_output=True,
                               text=True, timeout=5).stdout.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        ativo = None
    try:
        chave = "".join(c for c in LLAMA_KEY_FILE.read_bytes()[:32].decode("ascii", "ignore")
                        if c.islower() or c.isdigit()) or None
    except OSError:
        chave = None
    try:
        from app.services import local_model
        rotulo = local_model.MODELS.get(local_model.ALIASES.get(chave, chave)) if chave else None
    except Exception:
        rotulo = None
    memoria = {"total_mb": None, "disponivel_mb": None}
    try:
        for linha in Path("/proc/meminfo").read_text().splitlines():
            if linha.startswith("MemTotal:"):
                memoria["total_mb"] = int(linha.split()[1]) // 1024
            elif linha.startswith("MemAvailable:"):
                memoria["disponivel_mb"] = int(linha.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    processo_mb = None  # "indisponível" na tela quando não dá para ler
    try:
        pid = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True,
                             timeout=5).stdout.split()
        if pid:
            for linha in Path(f"/proc/{int(pid[0])}/status").read_text().splitlines():
                if linha.startswith("VmRSS:"):
                    processo_mb = int(linha.split()[1]) // 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        processo_mb = None
    return {"ativo": ativo, "chave": chave, "modelo": rotulo, "memoria": memoria,
            "processo_mb": processo_mb, "pasta": str(raiz()), "pasta_existe": raiz().is_dir()}


@router.get("/propostas")
def propostas():
    """Propostas por modelo (tmp/bancada/<modelo>/*.txt) e casos verificados."""
    vereditos: dict[str, list[dict]] = {}
    for r in _registros():
        if r.get("origem") == "observer":
            vereditos.setdefault(r["id"], []).append({"observer": r.get("observer"), "veredito": r.get("veredito")})
    itens = []
    for modelo in _modelos():
        resumo = _ler_json(raiz() / modelo / "_resumo.json") or {}
        for arquivo in sorted((raiz() / modelo).glob("*.txt")):
            ident = arquivo.stem
            if not NOME_VALIDO.match(ident):
                continue
            verificacao = _ler_json(raiz() / "verificacoes" / f"{ident}.json")
            info = resumo.get(ident) or {}
            itens.append({"id": ident, "modelo": modelo, "origem": "rodar",
                          "segundos": info.get("segundos"), "tokens": info.get("tokens"),
                          "verificado": verificacao is not None,
                          "achados": _contagem(verificacao.get("achados", [])) if verificacao else None,
                          "observers": vereditos.get(ident, [])})
    vistos = {(i["modelo"], i["id"]) for i in itens}
    pasta = raiz() / "verificacoes"
    if pasta.is_dir():
        for arquivo in sorted(pasta.glob("*.json")):
            dados = _ler_json(arquivo)
            if not dados or not NOME_VALIDO.match(str(dados.get("id", ""))) \
                    or not NOME_VALIDO.match(str(dados.get("modelo", ""))):
                continue
            if (dados["modelo"], dados["id"]) in vistos:
                continue
            itens.append({"id": dados["id"], "modelo": dados["modelo"], "origem": "corpus",
                          "segundos": None, "tokens": None, "verificado": True,
                          "esperado": dados.get("esperado"), "achados": _contagem(dados.get("achados", [])),
                          "observers": vereditos.get(dados["id"], [])})
    return {"propostas": _mascarar(itens)}


@router.get("/propostas/{modelo}/{ident}")
def proposta(modelo: str, ident: str):
    verificacao = None
    if NOME_VALIDO.match(ident):
        verificacao = _ler_json(_dentro("verificacoes", f"{ident}.json"))
    texto = None
    arquivo = _dentro(modelo, f"{ident}.txt")
    if arquivo.is_file():
        texto = arquivo.read_text(encoding="utf-8", errors="replace")[:LIMITE_TEXTO]
    elif verificacao and verificacao.get("modelo") == modelo:
        texto = str(verificacao.get("proposta") or "")[:LIMITE_TEXTO]
    if texto is None:
        raise HTTPException(404, "proposta não encontrada")
    return _mascarar({
        "id": ident, "modelo": modelo, "texto": texto,
        "verificacao": {"achados": verificacao.get("achados", []), "erros": verificacao.get("erros"),
                        "aprovada": verificacao.get("aprovada"), "tarefa": verificacao.get("tarefa"),
                        "esperado": verificacao.get("esperado"), "data": verificacao.get("data")}
        if verificacao else None,
        "pareceres": _pareceres(ident)})


@router.get("/resumo")
def resumo():
    """Aproveitamento por modelo e por quem avaliou (operador ou observer)."""
    ultimo = {(r["modelo"], r["id"], r.get("origem", "operador"), r.get("observer", "")): r for r in _registros()}
    grupos: dict[tuple[str, str], list[dict]] = {}
    for (modelo, _ident, origem, observer), r in ultimo.items():
        grupos.setdefault((modelo, observer or origem), []).append(r)
    linhas = []
    for (modelo, quem), itens in sorted(grupos.items()):
        tempos = _ler_json(raiz() / modelo / "_resumo.json") if NOME_VALIDO.match(modelo) else None
        segs = [tempos[r["id"]]["segundos"] for r in itens if tempos and r["id"] in tempos
                and isinstance(tempos[r["id"]], dict) and tempos[r["id"]].get("segundos") is not None]
        total = len(itens)
        linhas.append({"modelo": modelo, "avaliado_por": quem, "tarefas": total,
                       **{v: round(100 * sum(r.get("veredito") == v for r in itens) / total)
                          for v in ("aproveitada", "correcao_pequena", "descartada")},
                       "falhas": sum(r.get("veredito") == "falhou" for r in itens),
                       "tempo_medio_s": round(sum(segs) / len(segs), 1) if segs else None})
    return {"linhas": _mascarar(linhas)}
