"""Execução isolada ponta a ponta (ADR 005, fatias 3d e 3e).

Cobre o que o ADR promete e o que o plano de correção cobra como critério de
aceite: o gate roda DENTRO do worktree, o commit nasce no branch de build, a
árvore principal não se move, e `completed` continua inalcançável por aqui.
"""

import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import build_executor, build_worktree
from app.services.build_executor import execute_build
from app.services.test_gate import CheckResult, GateEvidence


def git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    origem = tmp_path / "repo"
    origem.mkdir()

    git(["init", "-b", "develop"], origem)
    git(["config", "user.email", "t@t.local"], origem)
    git(["config", "user.name", "Teste"], origem)

    (origem / "apps").mkdir()
    (origem / "apps" / "calc.py").write_text("def total(x):\n    return x\n")
    git(["add", "-A"], origem)
    git(["commit", "-m", "inicial"], origem)

    monkeypatch.setattr(build_worktree, "REPO_ROOT", origem)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")

    return origem


@pytest.fixture()
def run():
    return SimpleNamespace(
        id=uuid4(),
        backlog_id=uuid4(),
        agent="local-code",
    )


def resposta(**overrides) -> str:
    base = {
        "summary": "Corrige o total",
        "files": [
            {
                "path": "apps/calc.py",
                "content": "def total(x):\n    return x * 2\n",
            }
        ],
        "checks": ["pytest"],
    }
    base.update(overrides)
    return f"Aqui está:\n```json\n{json.dumps(base)}\n```"


def sha_de(repo_path, ref="HEAD"):
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo_path, capture_output=True, text=True
    ).stdout.strip()


class TestCaminhoFeliz:
    def test_produz_commit_no_branch(self, repo, run):
        resultado = execute_build(run, resposta(), run_gate=False)

        assert resultado.ok
        assert resultado.code == "build_committed"
        assert resultado.branch == f"build/{run.id}"
        assert resultado.commit_sha
        assert "apps/calc.py" in resultado.files

    def test_develop_nao_se_move(self, repo, run):
        antes = sha_de(repo, "develop")

        execute_build(run, resposta(), run_gate=False)

        assert sha_de(repo, "develop") == antes

    def test_branch_tem_o_commit_e_develop_nao(self, repo, run):
        resultado = execute_build(run, resposta(), run_gate=False)

        frente = subprocess.run(
            ["git", "log", "--oneline", f"develop..{resultado.branch}"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()

        atras = subprocess.run(
            ["git", "log", "--oneline", f"{resultado.branch}..develop"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()

        assert frente, "o branch de build precisa ter o commit"
        assert not atras, "develop não pode ter commit que o branch não tem"

    def test_conteudo_aplicado_no_branch(self, repo, run):
        resultado = execute_build(run, resposta(), run_gate=False)

        conteudo = subprocess.run(
            ["git", "show", f"{resultado.branch}:apps/calc.py"],
            cwd=repo, capture_output=True, text=True,
        ).stdout

        assert "x * 2" in conteudo

    def test_arquivo_da_arvore_principal_intacto(self, repo, run):
        execute_build(run, resposta(), run_gate=False)

        assert (repo / "apps" / "calc.py").read_text() == (
            "def total(x):\n    return x\n"
        )


class TestGateIsolado:
    def test_gate_roda_dentro_do_worktree(self, repo, run, monkeypatch):
        """O critério de aceite central: cwd do gate é o worktree."""
        capturado = {}

        def falso_gate(run_arg, paths):
            capturado["root"] = paths.root
            return GateEvidence(
                run_id=run_arg.id,
                backlog_id=run_arg.backlog_id,
                timestamp="2026-09-10T00:00:00+00:00",
                passed=True,
                checks=[CheckResult("pytest", True, True, "ok")],
            )

        monkeypatch.setattr(build_executor, "execute_gate", falso_gate)

        resultado = execute_build(run, resposta())

        assert resultado.gate_passed is True
        assert str(capturado["root"]).endswith(str(run.id))
        assert "/opt/workdev" != str(capturado["root"])

    def test_gate_reprovado_vai_para_blocked(self, repo, run, monkeypatch):
        def gate_falho(run_arg, paths):
            return GateEvidence(
                run_id=run_arg.id,
                backlog_id=run_arg.backlog_id,
                timestamp="2026-09-10T00:00:00+00:00",
                passed=False,
                mandatory_failed=["pytest"],
            )

        monkeypatch.setattr(build_executor, "execute_gate", gate_falho)

        resultado = execute_build(run, resposta())

        assert resultado.ok is True  # executou
        assert resultado.gate_passed is False
        assert resultado.next_status == "blocked"

    def test_gate_aprovado_vai_para_review_nunca_completed(
        self, repo, run, monkeypatch
    ):
        def gate_ok(run_arg, paths):
            return GateEvidence(
                run_id=run_arg.id,
                backlog_id=run_arg.backlog_id,
                timestamp="2026-09-10T00:00:00+00:00",
                passed=True,
            )

        monkeypatch.setattr(build_executor, "execute_gate", gate_ok)

        resultado = execute_build(run, resposta())

        assert resultado.next_status == "review"
        assert resultado.next_status != "completed"


class TestRecusas:
    def test_envelope_invalido_nao_cria_branch(self, repo, run):
        resultado = execute_build(run, "não sei fazer isso", run_gate=False)

        assert resultado.ok is False
        assert resultado.code == "no_json_found"
        assert resultado.next_status == "blocked"

        branches = subprocess.run(
            ["git", "branch", "--list", f"build/{run.id}"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        assert not branches

    def test_caminho_protegido_recusado_antes_de_tocar_disco(self, repo, run):
        resultado = execute_build(
            run,
            resposta(files=[{"path": ".env", "content": "SECRET=vazou"}]),
            run_gate=False,
        )

        assert resultado.ok is False
        assert resultado.code == "path_denied"
        assert not (repo / ".env").exists()

    def test_check_fora_do_allowlist_recusado(self, repo, run):
        resultado = execute_build(
            run, resposta(checks=["rm -rf /"]), run_gate=False
        )

        assert resultado.ok is False
        assert resultado.code == "check_not_allowed"

    def test_envelope_sem_arquivos(self, repo, run):
        resultado = execute_build(run, resposta(files=[]), run_gate=False)

        assert resultado.ok is False
        assert resultado.code == "envelope_without_changes"

    def test_mudanca_que_nao_muda_nada(self, repo, run):
        """Reescrever o conteúdo idêntico não vira commit vazio."""
        resultado = execute_build(
            run,
            resposta(
                files=[
                    {
                        "path": "apps/calc.py",
                        "content": "def total(x):\n    return x\n",
                    }
                ]
            ),
            run_gate=False,
        )

        assert resultado.ok is False
        assert resultado.code == "no_effective_change"

    def test_falha_inesperada_nao_vaza_excecao(self, repo, run, monkeypatch):
        def explode(*args, **kwargs):
            raise ValueError("erro interno qualquer")

        monkeypatch.setattr(build_worktree, "write_files", explode)
        monkeypatch.setattr(build_executor.build_worktree, "write_files", explode)

        resultado = execute_build(run, resposta(), run_gate=False)

        assert resultado.ok is False
        assert resultado.code == "build_failed"


class TestFlags:
    def test_desligado_por_padrao(self, monkeypatch):
        monkeypatch.delenv("WORKDEV_OLLAMA_BUILD_ENABLED", raising=False)
        assert build_executor.build_enabled() is False

    @pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "on"])
    def test_liga_com_valores_aceitos(self, monkeypatch, valor):
        monkeypatch.setenv("WORKDEV_OLLAMA_BUILD_ENABLED", valor)
        assert build_executor.build_enabled() is True

    def test_tentativas_tem_piso_e_teto(self, monkeypatch):
        monkeypatch.setenv("WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS", "0")
        assert build_executor.max_attempts() == 1

        monkeypatch.setenv("WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS", "999")
        assert build_executor.max_attempts() == 10

        monkeypatch.setenv("WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS", "abc")
        assert build_executor.max_attempts() == 3


class TestMensagemDeCommit:
    def test_nao_se_disfarca_de_humano(self, repo, run):
        resultado = execute_build(run, resposta(), run_gate=False)

        mensagem = subprocess.run(
            ["git", "log", "-1", "--format=%B", resultado.branch],
            cwd=repo, capture_output=True, text=True,
        ).stdout

        assert str(run.id) in mensagem
        assert "ADR 005" in mensagem
        assert "revisão independente pendente" in mensagem
