"""Testes de contrato DORA entre o pipeline de deploy e a API de outcomes.

Cobrem o certificado do backend DORA:
- artifact_fingerprint normalizado (prefixo "sha256:" removido) para
  nao estourar o max_length=64 do schema DeploymentOutcomeCreate;
- payload completo (proof_id, project, commit_sha, deployment_url,
  postcheck_result, error_message) compativel com o schema;
- leitura tolerante da chave dedicada /etc/workdev-deploy/api.key
  (PermissionError/OSError nao derruba o deploy);
- erro HTTP na persistencia tolerado (deploy nao falha por isso);
- semantica de falha: rollback bem-sucedido e rollback com falha
  persistem outcome rolled_back, este ultimo com error_message
  prefixado por "rollback_failed:".
"""

import importlib.util
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

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
FINGERPRINT_WITH_PREFIX = "sha256:" + "ab" * 32  # 71 chars -> precisa normalizar


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"{}"


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


def captured_payload(proof, monkeypatch, **kwargs):
    """Chama _persist_deployment_outcome e devolve o payload enviado a API."""
    sent = {}

    def fake_urlopen(req, timeout=0):
        sent["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    pipeline._persist_deployment_outcome(proof, "success", **kwargs)
    return sent["payload"]


def validate_against_schema(payload):
    """Valida o payload contra DeploymentOutcomeCreate, o contrato real da API."""
    from app.schemas.deployment import DeploymentOutcomeCreate

    return DeploymentOutcomeCreate(**payload)


def test_fingerprint_com_prefixo_sha256_e_normalizado(monkeypatch):
    proof = {
        "proof_id": "proof-1",
        "project": "workdev",
        "artifact_fingerprint": FINGERPRINT_WITH_PREFIX,
        "commit_sha": "cafe" * 16,
    }
    payload = captured_payload(proof, monkeypatch)
    assert payload["artifact_fingerprint"] == "ab" * 32
    assert len(payload["artifact_fingerprint"]) == 64
    validate_against_schema(payload)


def test_payload_completo_compativel_com_schema(monkeypatch):
    proof = {
        "proof_id": "proof-2",
        "project": "workdev",
        "artifact_fingerprint": FINGERPRINT_WITH_PREFIX,
        "commit_sha": "deadbeef" * 8,
    }
    payload = captured_payload(
        proof,
        monkeypatch,
        postcheck_result={"status": "DEPLOY_SUCCEEDED", "checks": {}},
    )
    for field in (
        "proof_id", "project", "artifact_fingerprint", "outcome",
        "commit_sha", "deployment_url", "postcheck_result", "error_message",
    ):
        assert field in payload
    assert payload["commit_sha"] == "deadbeef" * 8
    assert payload["postcheck_result"] == {"status": "DEPLOY_SUCCEEDED", "checks": {}}
    validate_against_schema(payload)


def test_api_key_inacessivel_nao_derruba(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(
        Path, "read_text",
        lambda self, **kw: (_ for _ in ()).throw(PermissionError("EACCES")),
    )
    sent = {}

    def fake_urlopen(req, timeout=0):
        sent["api_key_header"] = req.get_header("X-api-key")
        return FakeResponse()

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", fake_urlopen)
    pipeline._persist_deployment_outcome({"proof_id": "p", "project": "w"}, "success")
    assert sent["api_key_header"] == ""


def test_erro_http_na_persistencia_e_tolerado(monkeypatch):
    def raising_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Internal Server Error", {}, None
        )

    monkeypatch.setattr(pipeline.urllib.request, "urlopen", raising_urlopen)
    # Nao deve propagar excecao: persistencia nao pode falhar o deploy.
    pipeline._persist_deployment_outcome({"proof_id": "p", "project": "w"}, "success")


def _run_deploy_with_persistence_capture(tmp_path, monkeypatch, cb):
    repo, artifact, proof, approval = fixture(tmp_path)
    persisted = []
    monkeypatch.setattr(
        pipeline,
        "_persist_deployment_outcome",
        lambda proof, outcome, postcheck_result=None, error_message=None, **kw: (
            persisted.append(
                {
                    "outcome": outcome,
                    "postcheck_result": postcheck_result,
                    "error_message": error_message,
                }
            )
        ),
    )
    broker = pipeline.DeploymentPipeline(tmp_path / "state", KEY)
    status = broker.deploy(proof, approval, repo, artifact, "workdev", cb, now=1002)
    return status, persisted


def test_sucesso_persiste_outcome_success_com_postcheck(tmp_path, monkeypatch):
    status, persisted = _run_deploy_with_persistence_capture(
        tmp_path, monkeypatch, callbacks([], "DEPLOY_SUCCEEDED")
    )
    assert status == "DEPLOY_SUCCEEDED"
    assert persisted == [
        {
            "outcome": "success",
            "postcheck_result": {"status": "DEPLOY_SUCCEEDED"},
            "error_message": None,
        }
    ]


def test_rollback_bem_sucedido_persiste_rolled_back_sem_erro(tmp_path, monkeypatch):
    status, persisted = _run_deploy_with_persistence_capture(
        tmp_path, monkeypatch, callbacks(["x"], "DEPLOY_FAILED")
    )
    assert status == "DEPLOY_FAILED"
    assert persisted == [
        {
            "outcome": "rolled_back",
            "postcheck_result": {"status": "DEPLOY_FAILED"},
            "error_message": None,
        }
    ]


def test_rollback_com_falha_persiste_rolled_back_com_erro(tmp_path, monkeypatch):
    cb = callbacks([], "DEPLOY_FAILED")
    cb.rollback = lambda: (_ for _ in ()).throw(RuntimeError("rollback explodiu"))
    status, persisted = _run_deploy_with_persistence_capture(tmp_path, monkeypatch, cb)
    assert status == "DEPLOY_FAILED"
    assert len(persisted) == 1
    entry = persisted[0]
    assert entry["outcome"] == "rolled_back"
    assert entry["error_message"].startswith("rollback_failed:")
    assert "rollback explodiu" in entry["error_message"]


def test_falha_de_restart_tambem_persiste_outcome(tmp_path, monkeypatch):
    events = []
    cb = callbacks(events)
    cb.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart falhou"))
    status, persisted = _run_deploy_with_persistence_capture(tmp_path, monkeypatch, cb)
    assert status == "DEPLOY_FAILED"
    assert events == ["promote", "rollback"]
    assert len(persisted) == 1
    entry = persisted[0]
    assert entry["outcome"] == "rolled_back"
    assert entry["error_message"].startswith("deploy_failed:")
    assert "restart falhou" in entry["error_message"]


def test_falha_de_restart_com_rollback_falho_distingue_rollback_failed(
    tmp_path, monkeypatch
):
    cb = callbacks([])
    cb.restart = lambda: (_ for _ in ()).throw(RuntimeError("restart falhou"))
    cb.rollback = lambda: (_ for _ in ()).throw(RuntimeError("rollback explodiu"))
    status, persisted = _run_deploy_with_persistence_capture(tmp_path, monkeypatch, cb)
    assert status == "DEPLOY_FAILED"
    assert len(persisted) == 1
    assert persisted[0]["outcome"] == "rolled_back"
    assert persisted[0]["error_message"].startswith("rollback_failed:")
