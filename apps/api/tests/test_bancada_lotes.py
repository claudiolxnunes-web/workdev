"""Lotes da Bancada: id AAMMDD-NN, pasta única planos/ e rodar sem sobrescrever."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import bancada_runner as runner

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture
def local(tmp_path, monkeypatch):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    modulo = importlib.import_module("bancada_local")
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "x.py").write_text("".join(f"linha {i}\n" for i in range(1, 31)))
    monkeypatch.setattr(modulo, "REPO", repo)
    monkeypatch.setattr(modulo, "SAIDA", repo / "tmp" / "bancada")
    return modulo


def _plano(*ids):
    return json.dumps({"tarefas": [
        {"id": i, "instrucao": "Escreva a docstring da função do trecho abaixo.",
         "trechos": [["app/x.py", 1, 10]]} for i in ids]})


def test_proximo_lote(local, tmp_path):
    planos = tmp_path / "planos"
    assert local.proximo_lote(planos, "260105") == "260105-01"
    planos.mkdir()
    for nome in ("260105-01.json", "260105-03.json", "260104-09.json", "plano-123.json"):
        (planos / nome).write_text("{}")
    assert local.proximo_lote(planos, "260105") == "260105-04"
    assert local.proximo_lote(planos, "260106") == "260106-01"


def test_ids_genericos_levam_o_lote(local):
    plano = local._extrair_plano(_plano("1", "t2", "docstring_x", None), "260105-02")
    assert [t["id"] for t in plano["tarefas"]] == ["260105-02-01", "260105-02-02", "docstring_x", "260105-02-03"]


def test_planos_do_mesmo_dia_nao_repetem_ids(local):
    a = local._extrair_plano(_plano("1", "2"), "260105-01")
    b = local._extrair_plano(_plano("1", "2"), "260105-02")
    assert not {t["id"] for t in a["tarefas"]} & {t["id"] for t in b["tarefas"]}


def _args_rodar(arquivo, sobrescrever=False):
    return SimpleNamespace(tarefas=str(arquivo), so=None, stream=False, url="http://x",
                           timeout=1, sobrescrever=sobrescrever)


def test_rodar_pula_proposta_existente(local, monkeypatch, tmp_path, capsys):
    chamadas = []
    monkeypatch.setattr(local, "health", lambda url: True)
    monkeypatch.setattr(local, "modelo_ativo", lambda: "moe")
    monkeypatch.setattr(local, "chat", lambda url, corpo, timeout: chamadas.append(1) or
                        {"choices": [{"message": {"content": "nova"}}], "usage": {}})
    arquivo = tmp_path / "lote.json"
    arquivo.write_text(_plano("a", "b"))
    pasta = local.SAIDA / "moe"
    pasta.mkdir(parents=True)
    (pasta / "a.txt").write_text("antiga\n")

    assert local.cmd_rodar(_args_rodar(arquivo)) == 0
    assert (pasta / "a.txt").read_text() == "antiga\n"
    assert (pasta / "b.txt").read_text() == "nova\n"
    assert len(chamadas) == 1
    assert "[pulada] a" in capsys.readouterr().out

    assert local.cmd_rodar(_args_rodar(arquivo, sobrescrever=True)) == 0
    assert (pasta / "a.txt").read_text() == "nova\n"


def test_planejar_da_pagina_grava_em_planos_com_lote(tmp_path, monkeypatch, local):
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    planner = SimpleNamespace(planejar_stream=lambda *a: iter([{"tipo": "ok", "tarefas": [{"id": "x"}], "tokens": 5}]))
    monkeypatch.setattr(runner, "_modulo", lambda nome: {"bancada_planner": planner, "bancada_local": local}[nome])
    hoje = local.proximo_lote(tmp_path / "nada")[:6]

    eventos = [json.loads(e[5:]) for e in runner.planejar_stream(
        {"tarefa_id": None, "prompt": "p", "modelo": "m"})]

    assert eventos[-1]["id"] == f"{hoje}-01"
    gravado = json.loads((tmp_path / "bancada" / "planos" / f"{hoje}-01.json").read_text())
    assert gravado["lote"] == f"{hoje}-01" and gravado["tarefas"] == [{"id": "x"}]
    assert not (tmp_path / "bancada" / "planejamentos").exists()


# ---------------------------------------------------------------- validador compartilhado

def _tarefa(tid="", arquivos=("app/x.py",), fim=10, **extra):
    return {"id": tid, "instrucao": "Escreva a docstring da função do trecho abaixo.",
            "trechos": [[a, 1, fim] for a in arquivos], **extra}


def test_limites_do_ai_hub_sao_mais_largos_que_os_do_local(local):
    for nome in ("y.py", "z.py"):
        (local.REPO / "app" / nome).write_text("a\n" * 30)
    tres_arquivos = {"tarefas": [_tarefa(arquivos=("app/x.py", "app/y.py", "app/z.py"), max_tokens=2000)]}

    plano = local.validar_lote(json.loads(json.dumps(tres_arquivos)), "261005-01", local.LIMITES_AI_HUB)
    assert plano["tarefas"][0]["id"] == "261005-01-01"
    with pytest.raises(ValueError, match="mais de 2 arquivos"):
        local.validar_lote(json.loads(json.dumps(tres_arquivos)), "261005-01", local.LIMITES_LOCAL)


def test_ate_10_tarefas_e_um_lote_so(local):
    lotes = local.dividir_em_lotes({"tarefas": [_tarefa() for _ in range(10)]}, "261005-03", local.LIMITES_AI_HUB)
    assert [n for n, _ in lotes] == ["261005-03"]
    assert lotes[0][1]["tarefas"][-1]["id"] == "261005-03-10"


def test_de_11_a_20_divide_em_2_lotes_equilibrados(local):
    lotes = local.dividir_em_lotes({"tarefas": [_tarefa() for _ in range(15)], "obs": "x"},
                                   "261005-03", local.LIMITES_AI_HUB)
    assert [(n, len(p["tarefas"])) for n, p in lotes] == [("261005-03", 8), ("261005-04", 7)]
    assert lotes[1][1]["tarefas"][0]["id"] == "261005-04-01" and lotes[1][1]["obs"] == "x"


def test_acima_de_20_vai_para_o_backlog(local):
    with pytest.raises(ValueError, match="máximo de 20 tarefas.*backlog"):
        local.dividir_em_lotes({"tarefas": [_tarefa() for _ in range(21)]}, "261005-01", local.LIMITES_AI_HUB)


def test_id_descritivo_repetido_entre_lotes_e_recusado(local):
    tarefas = [_tarefa() for _ in range(11)] + [_tarefa("doc_x"), _tarefa("doc_x")]
    with pytest.raises(ValueError, match="id duplicado: doc_x"):
        local.dividir_em_lotes({"tarefas": tarefas}, "261005-01", local.LIMITES_AI_HUB)


def test_plano_vazio_continua_um_lote_vazio(local):
    lotes = local.dividir_em_lotes({"tarefas": [], "fora_do_alcance": "migração"}, "261005-01", local.LIMITES_AI_HUB)
    assert lotes == [("261005-01", {"tarefas": [], "fora_do_alcance": "migração"})]


def test_planejar_local_continua_com_teto_de_4(local):
    with pytest.raises(ValueError, match="máximo de 4 tarefas"):
        local._extrair_plano(json.dumps({"tarefas": [_tarefa() for _ in range(5)]}), "261005-01")


@pytest.mark.parametrize("tarefa, erro", [
    (_tarefa(fim=31), "linha 31 não existe"),
    (_tarefa(arquivos=("app/nao.py",)), "arquivo não existe"),
    (_tarefa(arquivos=(".env",)), "bloqueado"),
    (_tarefa(max_tokens=32), "max_tokens deve estar entre 64"),
    (_tarefa(exige={"current(": "x"}), "expressão inválida"),
    (_tarefa(trechos=[]), "precisa informar trechos"),
])
def test_validador_recusa_o_que_o_rodar_recusaria(local, tarefa, erro):
    with pytest.raises(ValueError, match=erro):
        local.validar_lote({"tarefas": [tarefa]}, "261005-01", local.LIMITES_AI_HUB)


def test_validador_usa_a_raiz_informada(local, tmp_path):
    outra = tmp_path / "checkout"
    (outra / "app").mkdir(parents=True)
    (outra / "app" / "so_aqui.py").write_text("a\n" * 5)
    plano = {"tarefas": [_tarefa(arquivos=("app/so_aqui.py",), fim=5)]}
    assert local.validar_lote(plano, "261005-01", local.LIMITES_AI_HUB, outra)["tarefas"]


# ---------------------------------------------------------------- extrair

@pytest.fixture
def repo_git(local):
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(local.REPO), *a], check=True, capture_output=True)
    git("init", "-q")
    git("add", "app/x.py")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return local


def _proposta(local, texto, tid="261005-01-01"):
    pasta = local.SAIDA / "moe"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{tid}.txt").write_text(texto)


DIFF = "```diff\n--- a/app/x.py\n+++ b/app/x.py\n@@ -1,3 +1,3 @@\n linha 1\n-linha 2\n+linha dois\n linha 3\n```\n"


def test_extrair_grava_patch_e_so_testa(repo_git, capsys):
    local = repo_git
    _proposta(local, "Segue:\n" + DIFF)
    assert local.cmd_extrair(SimpleNamespace(id="261005-01-01", modelo=None)) == 0
    patch = local.SAIDA / "patches" / "261005-01-01.patch"
    assert patch.read_text().startswith("--- a/app/x.py")
    assert "git -C" in capsys.readouterr().out
    assert "linha 2\n" in (local.REPO / "app" / "x.py").read_text()  # nunca aplica


def test_extrair_avisa_quando_nao_aplica(repo_git, capsys):
    local = repo_git
    _proposta(local, DIFF.replace("linha 2", "linha que nao existe"))
    assert local.cmd_extrair(SimpleNamespace(id="261005-01-01", modelo=None)) == 3
    assert "NÃO APLICA" in capsys.readouterr().out


@pytest.mark.parametrize("texto, tid, codigo", [
    ("FALTA: a definição de X", "261005-01-01", 1),
    (DIFF, "../fora", 1),
])
def test_extrair_recusa_sem_diff_ou_id_ruim(repo_git, texto, tid, codigo):
    _proposta(repo_git, texto)
    assert repo_git.cmd_extrair(SimpleNamespace(id=tid, modelo=None)) == codigo
