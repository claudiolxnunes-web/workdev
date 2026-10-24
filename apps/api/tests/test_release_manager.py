import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[3] / "scripts/deploy/release_manager.py"
spec = importlib.util.spec_from_file_location("release_manager", MODULE)
release = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["release_manager"] = release
spec.loader.exec_module(release)


def source_and_artifact(tmp_path):
    source = tmp_path / "source"
    artifact = tmp_path / "artifact"
    source.mkdir()
    artifact.mkdir()
    (source / "apps/api/app").mkdir(parents=True)
    (source / "apps/api/app/main.py").write_text("ok = True\n")
    (artifact / "index.html").write_text("bundle")
    subprocess.run(["git", "init", "-q", source], check=True)
    subprocess.run(["git", "-C", source, "config", "user.email", "gate@test"], check=True)
    subprocess.run(["git", "-C", source, "config", "user.name", "Gate Test"], check=True)
    subprocess.run(["git", "-C", source, "add", "."], check=True)
    subprocess.run(["git", "-C", source, "commit", "-qm", "fixture"], check=True)
    return source, artifact


def test_release_contem_commit_e_artefato(tmp_path):
    source, artifact = source_and_artifact(tmp_path)
    manager = release.ReleaseManager(tmp_path / "runtime", runtime_gid=os.getgid())

    created = manager.prepare(source, artifact, "proof-1")

    assert (created / "apps/api/app/main.py").exists()
    assert (created / "apps/web/dist/index.html").read_text() == "bundle"
    assert (created.stat().st_mode & 0o777) == 0o750
    assert ((created / "apps/api/app/main.py").stat().st_mode & 0o777) == 0o640
    assert ((created / "apps/web/dist/index.html").stat().st_mode & 0o777) == 0o640
    assert created.stat().st_gid == os.getgid()
    assert (created / "apps/api/app/main.py").stat().st_gid == os.getgid()


def test_promocao_e_rollback_trocam_links_atomicamente(tmp_path):
    source, artifact = source_and_artifact(tmp_path)
    manager = release.ReleaseManager(tmp_path / "runtime")
    first = manager.prepare(source, artifact, "first")
    second = manager.prepare(source, artifact, "second")

    manager.promote(first)
    manager.promote(second)
    assert manager.current.resolve() == second
    assert manager.previous.resolve() == first

    manager.rollback()
    assert manager.current.resolve() == first
    assert manager.previous.resolve() == second


def test_release_nao_pode_ser_preparada_duas_vezes(tmp_path):
    source, artifact = source_and_artifact(tmp_path)
    manager = release.ReleaseManager(tmp_path / "runtime")
    manager.prepare(source, artifact, "same")

    with pytest.raises(release.ReleaseError, match="ja existe"):
        manager.prepare(source, artifact, "same")


def test_release_rejeita_promocao_fora_da_raiz(tmp_path):
    manager = release.ReleaseManager(tmp_path / "runtime")
    manager.releases.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(release.ReleaseError, match="fora da raiz"):
        manager.promote(outside)
