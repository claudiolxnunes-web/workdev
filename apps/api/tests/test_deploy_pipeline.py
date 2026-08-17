import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


DEPLOY_DIR = Path(__file__).parents[3] / "scripts/deploy"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(DEPLOY_DIR))
proofs = load("deploy_proof")
pipeline = load("pipeline")

KEY = b"k" * 32


def fixture(tmp_path):
    repo = tmp_path / "repo"
    artifact = tmp_path / "artifact"
    repo.mkdir()
    artifact.mkdir()
    (repo / "app.py").write_text("ok\n")
    (artifact / "index.html").write_text("ok\n")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "gate@test"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Gate Test"], check=True)
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "fixture"], check=True)
    proof = proofs.issue_proof(repo, artifact, "workdev", KEY, now=1000)
    approval = pipeline.issue_approval(proof, "claudio", KEY, now=1001)
    return repo, artifact, proof, approval


def callbacks(events, status="DEPLOY_SUCCEEDED"):
    return pipeline.DeploymentCallbacks(
        promote=lambda: events.append("promote"),
        restart=lambda: events.append("restart"),
        postcheck=lambda: {"status": status},
        rollback=lambda: events.append("rollback"),
    )


def test_prova_sem_aprovacao_valida_e_recusada(tmp_path):
    repo, artifact, proof, approval = fixture(tmp_path)
    approval["actor"] = "invasor"
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)

    with pytest.raises(pipeline.PipelineError, match="assinatura"):
        broker.deploy(proof, approval, repo, artifact, "workdev", callbacks([]), now=1002)


def test_prova_e_consumida_uma_unica_vez(tmp_path):
    repo, artifact, proof, approval = fixture(tmp_path)
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)

    assert broker.deploy(proof, approval, repo, artifact, "workdev", callbacks([]), now=1002) == "DEPLOY_SUCCEEDED"
    with pytest.raises(pipeline.PipelineError, match="File exists"):
        broker.deploy(proof, approval, repo, artifact, "workdev", callbacks([]), now=1003)


def test_codigo_mudou_apos_aprovacao_e_recusado(tmp_path):
    repo, artifact, proof, approval = fixture(tmp_path)
    (repo / "app.py").write_text("mudou")
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)

    with pytest.raises(pipeline.PipelineError, match="nao esta limpa"):
        broker.deploy(proof, approval, repo, artifact, "workdev", callbacks([]), now=1002)


def test_falha_de_restart_dispara_rollback(tmp_path):
    repo, artifact, proof, approval = fixture(tmp_path)
    events = []
    cb = callbacks(events)
    cb.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart falhou"))
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)

    assert broker.deploy(proof, approval, repo, artifact, "workdev", cb, now=1002) == "DEPLOY_FAILED"
    assert events == ["promote", "rollback"]


def test_pos_gate_degradado_nao_declara_sucesso(tmp_path):
    repo, artifact, proof, approval = fixture(tmp_path)
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)

    assert broker.deploy(proof, approval, repo, artifact, "workdev", callbacks([], "DEPLOY_DEGRADED"), now=1002) == "DEPLOY_DEGRADED"
