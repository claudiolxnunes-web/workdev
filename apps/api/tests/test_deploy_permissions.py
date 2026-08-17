import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parents[3]
MODULE = ROOT / "scripts/deploy/permission_contract.py"
spec = importlib.util.spec_from_file_location("permission_contract", MODULE)
permissions = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["permission_contract"] = permissions
spec.loader.exec_module(permissions)


def test_api_workdev_consegue_ler_release():
    assert permissions.RELEASE_FILE.allows(permissions.WORKDEV_API, "read")


def test_api_workdev_consegue_atravessar_current_apps_api():
    chain = [
        permissions.RUNTIME,
        permissions.RELEASES,
        permissions.RELEASE_DIRECTORY,
        permissions.RELEASE_DIRECTORY,
        permissions.RELEASE_DIRECTORY,
    ]
    assert all(path.allows(permissions.WORKDEV_API, "execute") for path in chain)


def test_workdev_nao_cria_arquivo_na_release():
    assert not permissions.RELEASE_DIRECTORY.allows(
        permissions.WORKDEV_AGENT, "write"
    )


def test_workdev_nao_altera_release_existente():
    assert not permissions.RELEASE_FILE.allows(permissions.WORKDEV_AGENT, "write")


def test_workdev_nao_troca_current():
    assert not permissions.RUNTIME.allows(permissions.WORKDEV_AGENT, "write")


def test_workdev_nao_troca_previous():
    assert not permissions.RUNTIME.allows(permissions.WORKDEV_AGENT, "write")


def test_workdev_deploy_prepara_e_promove():
    assert permissions.RELEASES.allows(permissions.WORKDEV_DEPLOY, "write")
    assert permissions.RUNTIME.allows(permissions.WORKDEV_DEPLOY, "write")


def test_unit_api_recebe_grupo_somente_no_processo_do_servico():
    unit = (ROOT / "scripts/deploy/systemd/workdev-api.service").read_text()
    assert "User=workdev" in unit
    assert "Group=workdev" in unit
    assert "SupplementaryGroups=workdev-runtime" in unit
    assert "WorkingDirectory=/opt/workdev-runtime/current/apps/api" in unit


def test_agentes_nao_recebem_grupo_do_runtime():
    for name in ("workdev-agents.service", "workdev-agents-health.service"):
        unit = (ROOT / "scripts/deploy/systemd" / name).read_text()
        assert "SupplementaryGroups=workdev-runtime" not in unit


def test_workdev_nao_le_estado_provas_approvals_ou_chave():
    for path in (
        "/var/lib/workdev-deploy",
        "/etc/workdev-deploy/signing.key",
    ):
        contract = permissions.PATHS[path]
        assert not contract.allows(permissions.WORKDEV_AGENT, "read")
        assert not contract.allows(permissions.WORKDEV_AGENT, "write")


def test_workdev_nao_altera_codigo_ou_clientes_privilegiados():
    for path in (
        "/usr/local/lib/workdev-deploy",
        "/usr/local/sbin/workdev-deployctl",
        "/usr/local/libexec/workdev-deploy-readcheck",
    ):
        assert not permissions.PATHS[path].allows(
            permissions.WORKDEV_AGENT, "write"
        )


def test_secrets_operacionais_nao_sao_acessiveis_ao_deploy():
    for path in (
        "/home/workdev",
        "/etc/workdev/workdev-api.env",
        "/etc/workdev/agents-alert.env",
    ):
        assert not permissions.PATHS[path].allows(
            permissions.WORKDEV_DEPLOY, "read"
        )


def test_workdev_pode_usar_venv_sem_alterar_dependencias():
    venv = permissions.PATHS["/opt/workdev/apps/api/venv"]
    assert venv.allows(permissions.WORKDEV_AGENT, "read")
    assert venv.allows(permissions.WORKDEV_AGENT, "execute")
    assert not venv.allows(permissions.WORKDEV_AGENT, "write")


def test_broker_le_codigo_fonte_sem_poder_altera_lo():
    checkout = permissions.PATHS["/opt/workdev"]
    assert checkout.allows(permissions.WORKDEV_DEPLOY, "read")
    assert checkout.allows(permissions.WORKDEV_DEPLOY, "execute")
    assert not checkout.allows(permissions.WORKDEV_DEPLOY, "write")


def test_sudoers_workdev_tem_somente_leitura_fixa_da_porta():
    policy = (
        ROOT / "scripts/deploy/systemd/workdev-deploy.sudoers"
    ).read_text()
    effective = [line for line in policy.splitlines() if line and not line.startswith("#")]
    assert effective
    workdev_rules = [line for line in effective if line.startswith("workdev ")]
    assert workdev_rules == [
        "workdev ALL=(root) NOPASSWD: "
        "/usr/local/libexec/workdev-deploy-readcheck port"
    ]
    assert all(
        line.startswith(("workdev-deploy ", "workdev ")) for line in effective
    )
