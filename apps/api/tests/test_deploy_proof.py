import importlib.util
import subprocess
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[3] / "scripts/deploy/deploy_proof.py"
SPEC = importlib.util.spec_from_file_location("deploy_proof", MODULE_PATH)
proofs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(proofs)


KEY = b"k" * 32


def repo_with_artifact(tmp_path: Path):
    repo = tmp_path / "repo"
    artifact = tmp_path / "artifact"
    repo.mkdir()
    artifact.mkdir(parents=True)
    (repo / "app.py").write_text("answer = 42\n")
    (artifact / "index.html").write_text("ok")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "gate@test"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Gate Test"], check=True)
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "fixture"], check=True)
    return repo, artifact


def issue(tmp_path: Path, now=1000):
    repo, artifact = repo_with_artifact(tmp_path)
    proof = proofs.issue_proof(repo, artifact, "workdev", KEY, now=now)
    return repo, artifact, proof


def test_prova_valida_para_o_mesmo_estado(tmp_path):
    repo, artifact, proof = issue(tmp_path)

    proofs.verify_proof(proof, repo, artifact, "workdev", KEY, now=1001)


def test_arvore_suja_nao_emite_prova(tmp_path):
    repo, artifact = repo_with_artifact(tmp_path)
    (repo / "app.py").write_text("changed")

    with pytest.raises(proofs.ProofError, match="nao esta limpa"):
        proofs.issue_proof(repo, artifact, "workdev", KEY, now=1000)


def test_prova_expirada_e_recusada(tmp_path):
    repo, artifact, proof = issue(tmp_path)

    with pytest.raises(proofs.ProofError, match="expirada"):
        proofs.verify_proof(proof, repo, artifact, "workdev", KEY, now=2000)


def test_assinatura_forjada_e_recusada(tmp_path):
    repo, artifact, proof = issue(tmp_path)
    proof["project"] = "feed-bpf"

    with pytest.raises(proofs.ProofError, match="assinatura invalida"):
        proofs.verify_proof(proof, repo, artifact, "feed-bpf", KEY, now=1001)


def test_prova_de_outro_projeto_e_recusada(tmp_path):
    repo, artifact, proof = issue(tmp_path)

    with pytest.raises(proofs.ProofError, match="outro projeto"):
        proofs.verify_proof(proof, repo, artifact, "feed-bpf", KEY, now=1001)


def test_codigo_alterado_invalida_prova(tmp_path):
    repo, artifact, proof = issue(tmp_path)
    (repo / "app.py").write_text("changed")

    with pytest.raises(proofs.ProofError, match="nao esta limpa"):
        proofs.verify_proof(proof, repo, artifact, "workdev", KEY, now=1001)


def test_artefato_alterado_invalida_prova(tmp_path):
    repo, artifact, proof = issue(tmp_path)
    (artifact / "index.html").write_text("changed")

    with pytest.raises(proofs.ProofError, match="artefato mudou"):
        proofs.verify_proof(proof, repo, artifact, "workdev", KEY, now=1001)


def test_ttl_fora_do_limite_e_recusado(tmp_path):
    repo, artifact = repo_with_artifact(tmp_path)

    with pytest.raises(proofs.ProofError, match="validade"):
        proofs.issue_proof(repo, artifact, "workdev", KEY, ttl_seconds=0, now=1000)
