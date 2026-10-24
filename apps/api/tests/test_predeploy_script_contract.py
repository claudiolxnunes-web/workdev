from pathlib import Path


ROOT = Path(__file__).parents[3]
SCRIPT = (ROOT / "verificar-deploy.sh").read_text()


def test_documentacao_usa_nome_real_do_script():
    assert "/opt/workdev/verificacao.sh" not in SCRIPT
    assert "/opt/workdev/verificar-deploy.sh" in SCRIPT


def test_build_falho_e_bloqueador():
    assert 'if saida=$(cd "$WEB" && pnpm build' in SCRIPT
    assert 'bloqueia "pnpm build falhou:"' in SCRIPT


def test_venv_ausente_e_bloqueador():
    assert 'bloqueia "venv da API nao encontrado' in SCRIPT
    assert 'avisa "venv da API nao encontrado' not in SCRIPT


def test_gitleaks_ausente_e_bloqueador():
    assert 'bloqueia "gitleaks nao instalado' in SCRIPT
    assert "--redact" in SCRIPT


def test_porta_falha_fechada():
    assert 'bloqueia "nao foi possivel consultar MainPID' in SCRIPT
    assert 'bloqueia "nao foi possivel consultar processos na porta 8000' in SCRIPT


def test_veredito_tem_somente_exit_zero_ou_um():
    lines = {line.strip() for line in SCRIPT.splitlines() if line.strip().startswith("exit ")}
    assert lines == {"exit 0", "exit 1"}


def test_script_nao_executa_acoes_destrutivas():
    executable = "\n".join(
        line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("git push", "systemctl restart", "systemctl stop", "rm -"):
        assert forbidden not in executable
