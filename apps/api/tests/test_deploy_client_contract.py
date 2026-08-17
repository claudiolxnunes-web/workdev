from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPT = (ROOT / "deploy.sh").read_text(encoding="utf-8")
CONTROLLER = (
    ROOT / "scripts/deploy/workdev-deployctl"
).read_text(encoding="utf-8")
SUDOERS = (
    ROOT / "scripts/deploy/systemd/workdev-deploy.sudoers"
).read_text(encoding="utf-8")
READCHECK = (
    ROOT / "scripts/deploy/workdev-deploy-readcheck"
).read_text(encoding="utf-8")


def test_deploy_cliente_exige_prova_e_usuario_dedicado():
    assert "<proof_id>" in SCRIPT
    assert "EUID" in SCRIPT
    assert "/usr/local/sbin/workdev-deployctl" in SCRIPT
    assert "root:root:755" in SCRIPT


def test_deploy_cliente_nao_builda_nem_reinicia_diretamente():
    assert "pnpm" not in SCRIPT
    assert "systemctl" not in SCRIPT
    assert "verificar-deploy.sh" not in SCRIPT
    assert "/opt/workdev/scripts/deploy/deploy_broker.py" not in SCRIPT


def test_sudoers_nao_concede_sudo_generico_ou_start_stop():
    lines = [line for line in SUDOERS.splitlines() if line and not line.startswith("#")]
    assert lines
    assert all("NOPASSWD: ALL" not in line for line in lines)
    assert all(" systemctl start " not in line for line in lines)
    assert all(" systemctl stop " not in line for line in lines)
    assert any("systemctl restart workdev-api.service" in line for line in lines)


def test_helper_privilegiado_tem_apenas_leituras_fixadas():
    assert "case" in READCHECK
    assert "/usr/bin/ss -H -ltnp 'sport = :8000'" in READCHECK
    assert "/usr/bin/journalctl -u workdev-api" in READCHECK
    for forbidden in ("rm ", "systemctl", "deploy.sh", "git push"):
        assert forbidden not in READCHECK


def test_controlador_executa_copia_imutavel_com_usuario_dedicado():
    assert "/usr/local/lib/workdev-deploy/deploy_broker.py" in CONTROLLER
    assert "root:root:755" in CONTROLLER
    assert "runuser -u workdev-deploy" in CONTROLLER
    assert "/opt/workdev/scripts/deploy/deploy_broker.py" not in CONTROLLER


def test_manifest_instala_gate_e_broker_fora_da_arvore_mutavel():
    manifest = (ROOT / "scripts/deploy/install-manifest.txt").read_text()
    assert "/usr/local/lib/workdev-deploy/deploy_broker.py root:root:0755" in manifest
    assert "/usr/local/lib/workdev-deploy/verificar-deploy.sh root:root:0755" in manifest
    assert "deploy.sh /opt/workdev/deploy.sh root:root:0755+immutable" in manifest
