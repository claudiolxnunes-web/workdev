"""Isolamento do Build em worktree efêmero (ADR 005, fatia 3c).

A garantia central: a árvore principal do repositório não é tocada, nem no
caminho feliz nem quando a execução falha no meio.
"""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import build_worktree
from app.services.build_envelope import BuildEnvelope
from app.services.build_worktree import (
    WorktreeError,
    ephemeral_worktree,
    write_files,
)


def git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """Repositório git de verdade — worktree não funciona com mock."""
    origem = tmp_path / "repo"
    origem.mkdir()

    git(["init", "-b", "develop"], origem)
    git(["config", "user.email", "t@t.local"], origem)
    git(["config", "user.name", "Teste"], origem)

    (origem / "arquivo.txt").write_text("original\n")
    (origem / "apps").mkdir()
    (origem / "apps" / "api.py").write_text("versao = 1\n")
    git(["add", "-A"], origem)
    git(["commit", "-m", "inicial"], origem)

    monkeypatch.setattr(build_worktree, "REPO_ROOT", origem)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")

    return origem


def sha_de(repo_path, ref="HEAD"):
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestCicloDeVida:
    def test_cria_e_remove(self, repo):
        run_id = str(uuid4())

        with ephemeral_worktree(run_id, repo=repo) as wt:
            assert wt.path.exists()
            assert wt.branch == f"build/{run_id}"
            caminho = wt.path

        assert not caminho.exists()

    def test_arvore_principal_intacta(self, repo):
        antes = sha_de(repo)
        conteudo_antes = (repo / "arquivo.txt").read_text()

        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            (wt.path / "arquivo.txt").write_text("mexido pelo agente\n")
            build_worktree.commit(wt, "muda arquivo")

        assert sha_de(repo) == antes
        assert (repo / "arquivo.txt").read_text() == conteudo_antes

    def test_branch_sobrevive_para_inspecao(self, repo):
        run_id = str(uuid4())

        with ephemeral_worktree(run_id, repo=repo) as wt:
            (wt.path / "novo.txt").write_text("x\n")
            build_worktree.commit(wt, "adiciona novo")

        # Diretório some, branch fica.
        assert sha_de(repo, f"build/{run_id}")

    def test_excecao_no_meio_nao_deixa_diretorio(self, repo):
        run_id = str(uuid4())
        capturado = {}

        with pytest.raises(RuntimeError):
            with ephemeral_worktree(run_id, repo=repo) as wt:
                capturado["path"] = wt.path
                raise RuntimeError("falha simulada no meio do build")

        assert not capturado["path"].exists()
        assert sha_de(repo) == sha_de(repo, "develop")

    def test_run_repetida_reaproveita_sem_conflito(self, repo):
        """Sobra de execução anterior não pode travar a próxima."""
        run_id = str(uuid4())

        for _ in range(2):
            with ephemeral_worktree(run_id, repo=repo) as wt:
                (wt.path / "a.txt").write_text("x\n")
                build_worktree.commit(wt, "commit")


class TestWriteFiles:
    def test_escreve_cria_e_deleta(self, repo):
        envelope = BuildEnvelope(
            summary="mexe em arquivos",
            files=[
                {"path": "apps/api.py", "content": "versao = 2\n"},
                {"path": "novo/sub.py", "action": "create", "content": "ok\n"},
                {"path": "arquivo.txt", "action": "delete"},
            ],
        )

        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            tocados = write_files(wt, envelope)

            assert (wt.path / "apps/api.py").read_text() == "versao = 2\n"
            assert (wt.path / "novo/sub.py").read_text() == "ok\n"
            assert not (wt.path / "arquivo.txt").exists()
            assert len(tocados) == 3

    def test_symlink_para_fora_e_recusado(self, repo, tmp_path):
        """String validada não basta: o link resolve para fora da árvore."""
        alvo_fora = tmp_path / "fora"
        alvo_fora.mkdir()

        envelope = BuildEnvelope(
            summary="tenta escapar por symlink",
            files=[{"path": "escape/x.py", "content": "malicioso\n"}],
        )

        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            (wt.path / "escape").symlink_to(alvo_fora)

            with pytest.raises(WorktreeError) as exc:
                write_files(wt, envelope)

            assert exc.value.code == "path_escapes_worktree"
            assert not (alvo_fora / "x.py").exists()

    def test_update_sem_conteudo_recusado(self, repo):
        """`content` é opcional no schema (delete não usa), então quem cobra
        a coerência com a ação é o write_files."""
        envelope = BuildEnvelope(
            summary="update sem conteúdo",
            files=[{"path": "apps/api.py", "action": "update"}],
        )

        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            with pytest.raises(WorktreeError) as exc:
                write_files(wt, envelope)
            assert exc.value.code == "content_missing"


class TestCommit:
    def test_sem_mudanca_nao_ha_o_que_commitar(self, repo):
        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            assert build_worktree.has_changes(wt) is False

    def test_detecta_mudanca(self, repo):
        with ephemeral_worktree(str(uuid4()), repo=repo) as wt:
            (wt.path / "arquivo.txt").write_text("diferente\n")
            assert build_worktree.has_changes(wt) is True

    def test_autor_do_commit_nao_se_passa_por_humano(self, repo):
        run_id = str(uuid4())

        with ephemeral_worktree(run_id, repo=repo) as wt:
            (wt.path / "x.txt").write_text("1\n")
            build_worktree.commit(wt, "mudança do agente")

        autor = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>", f"build/{run_id}"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout.strip()

        assert autor == (
            f"{build_worktree.COMMIT_AUTHOR_NAME} "
            f"<{build_worktree.COMMIT_AUTHOR_EMAIL}>"
        )


class TestAmbienteDoWorktree:
    """`node_modules` e config do Vite dentro do worktree (achado 4).

    Sem eles o gate não roda: vitest e vite build são obrigatórios, e todo build
    caía em `blocked` por ambiente ausente — não por código ruim.
    """

    def test_liga_dependencias_e_copia_config(self, repo, tmp_path):
        (repo / "node_modules").mkdir()
        (repo / "apps/web/node_modules").mkdir(parents=True)
        (repo / "apps/web/.env").write_text("VITE_X=1\n")
        (repo / "apps/web/.env.production").write_text("VITE_API_URL=\n")

        destino = tmp_path / "wt"
        destino.mkdir()

        info = build_worktree._preparar_ambiente(destino, repo)

        assert "node_modules" in info["links"]
        assert "apps/web/node_modules" in info["links"]
        assert (destino / "node_modules").is_symlink()
        assert "apps/web/.env" in info["config"]
        assert (destino / "apps/web/.env").read_text() == "VITE_X=1\n"
        # Cópia, não link: o build escreve no worktree e não pode alcançar a
        # config do repositório real.
        assert not (destino / "apps/web/.env").is_symlink()

    def test_nao_leva_env_local(self, repo, tmp_path):
        """`.env.local` tem precedência no Vite e já vazou localhost em bundle
        de produção uma vez — está registrado no CLAUDE.md."""
        (repo / "apps/web").mkdir(parents=True, exist_ok=True)
        (repo / "apps/web/.env.local").write_text("VITE_API_URL=localhost:8000\n")

        destino = tmp_path / "wt"
        destino.mkdir()

        info = build_worktree._preparar_ambiente(destino, repo)

        assert "apps/web/.env.local" not in info["config"]
        assert not (destino / "apps/web/.env.local").exists()

    def test_config_e_lista_explicita_sem_env_da_api(self):
        """O worktree não precisa de credencial de banco para rodar o gate."""
        assert not any(
            alvo.startswith("apps/api/") for alvo in build_worktree.CONFIG_FILES
        )
        assert all(
            alvo.startswith("apps/web/") for alvo in build_worktree.CONFIG_FILES
        )


class TestCommitNaoLevaAmbiente:
    """O commit contém o envelope, e só ele (validação de 2026-09-10).

    `git add -A` varria o que `_preparar_ambiente` cria para o gate rodar. O
    symlink `node_modules` entrou num commit de build de verdade: o `.gitignore`
    não o barra porque o padrão é `node_modules/`, com barra, que casa diretório
    e não casa symlink. O mesmo valeria para a config copiada.
    """

    def test_symlink_de_ambiente_nao_entra_no_commit(self, repo, tmp_path):
        from app.services.build_worktree import commit, ephemeral_worktree

        (repo / "node_modules").mkdir()

        with ephemeral_worktree(str(uuid4())) as wt:
            (wt.path / "novo.txt").write_text("conteudo\n")
            assert (wt.path / "node_modules").is_symlink()

            sha = commit(wt, "teste", paths=["novo.txt"])

            listados = git(
                ["show", "--name-only", "--format=", sha], wt.path
            ).stdout

        assert "novo.txt" in listados
        assert "node_modules" not in listados

    def test_sem_paths_mantem_o_comportamento_antigo(self, repo):
        from app.services.build_worktree import commit, ephemeral_worktree

        with ephemeral_worktree(str(uuid4())) as wt:
            (wt.path / "a.txt").write_text("a\n")
            sha = commit(wt, "teste")
            listados = git(
                ["show", "--name-only", "--format=", sha], wt.path
            ).stdout

        assert "a.txt" in listados
