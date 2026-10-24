import importlib.util
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).parents[3] / "scripts/deploy/predeploy_checks.py"
SPEC = importlib.util.spec_from_file_location("predeploy_checks", MODULE_PATH)
checks = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(checks)


def init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.email", "gate@test"], check=True)
    subprocess.run(["git", "-C", tmp_path, "config", "user.name", "Gate Test"], check=True)
    return tmp_path


def track(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "-C", repo, "add", relative], check=True)


def test_secret_scanner_reports_filename_without_value(tmp_path):
    repo = init_repo(tmp_path)
    secret = "sb_" + "secret_" + "A" * 24
    track(repo, "config.py", f'TOKEN = "{secret}"')

    assert checks.secret_files(repo) == ["config.py"]


def test_secret_scanner_ignores_untracked_file(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "local.txt").write_text("github_pat_" + "A" * 40)

    assert checks.secret_files(repo) == []


def test_env_versionado_bloqueia(tmp_path):
    repo = init_repo(tmp_path)
    track(repo, ".env", "SAFE=fake")

    assert checks.secret_files(repo) == [".env"]


def test_python_syntax_sem_gerar_pycache(tmp_path):
    valid = tmp_path / "valid.py"
    valid.write_text("answer = 42\n")

    assert checks.python_syntax_errors([tmp_path]) == []
    assert not (tmp_path / "__pycache__").exists()


def test_python_invalido_bloqueia(tmp_path):
    (tmp_path / "broken.py").write_text("def broken(:\n")

    assert checks.python_syntax_errors([tmp_path])


def test_porta_conta_pids_unicos_mesmo_na_mesma_linha():
    output = 'LISTEN users:(("uvicorn",pid=10,fd=6),("python",pid=20,fd=7))'

    assert checks.listening_pids(output) == {10, 20}


def test_porta_ignora_pid_repetido():
    output = "pid=10,fd=6 pid=10,fd=7"

    assert checks.listening_pids(output) == {10}


def test_porta_exige_mainpid_quando_servico_esta_ativo():
    assert checks.valid_port_pids({10}, 10)
    assert not checks.valid_port_pids(set(), 10)
    assert not checks.valid_port_pids({20}, 10)


def test_porta_sem_servico_aceita_ausencia_de_listener():
    assert checks.valid_port_pids(set(), 0)


def test_escopo_detecta_escape_da_raiz(tmp_path):
    assert checks.paths_outside_root(tmp_path, ["apps/api", "../fora"]) == ["../fora"]
