#!/usr/bin/env python3
"""Prepara e promove releases imutaveis fora da arvore de trabalho."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


class ReleaseError(RuntimeError):
    pass


class ReleaseManager:
    def __init__(self, runtime_root: Path, runtime_gid: int | None = None):
        self.runtime_root = runtime_root
        self.runtime_gid = runtime_gid
        self.releases = runtime_root / "releases"
        self.current = runtime_root / "current"
        self.previous = runtime_root / "previous"

    def prepare(self, source_root: Path, artifact_dir: Path, release_id: str) -> Path:
        self.releases.mkdir(parents=True, exist_ok=True)
        destination = self.releases / release_id
        if destination.exists():
            raise ReleaseError("release ja existe")
        temporary = self.releases / f".{release_id}.{os.getpid()}.tmp"
        temporary.mkdir(mode=0o750)
        try:
            archive = subprocess.run(
                ["git", "-C", str(source_root), "archive", "--format=tar", "HEAD"],
                check=True,
                capture_output=True,
            ).stdout
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
                tar.extractall(temporary, filter="data")
            web_dist = temporary / "apps/web/dist"
            web_dist.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(artifact_dir, web_dist)
            self._normalize_release_permissions(temporary, self.runtime_gid)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return destination

    @staticmethod
    def _normalize_release_permissions(root: Path, runtime_gid: int | None) -> None:
        """Grupo pode ler/atravessar; somente o owner pode modificar."""
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                continue
            if runtime_gid is not None:
                os.chown(path, -1, runtime_gid)
            if path.is_dir():
                path.chmod(0o750)
            elif path.is_file():
                executable = bool(path.stat().st_mode & 0o111)
                path.chmod(0o750 if executable else 0o640)
        if runtime_gid is not None:
            os.chown(root, -1, runtime_gid)
        root.chmod(0o750)

    @staticmethod
    def _target(link: Path) -> Path | None:
        return link.resolve() if link.is_symlink() else None

    @staticmethod
    def _replace_link(link: Path, target: Path) -> None:
        temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(target)
        os.replace(temporary, link)

    def promote(self, release: Path) -> None:
        resolved = release.resolve(strict=True)
        if not resolved.is_relative_to(self.releases.resolve(strict=True)):
            raise ReleaseError("release fora da raiz permitida")
        current_target = self._target(self.current)
        if current_target is not None:
            self._replace_link(self.previous, current_target)
        self._replace_link(self.current, resolved)

    def rollback(self) -> None:
        previous_target = self._target(self.previous)
        if previous_target is None:
            raise ReleaseError("release anterior indisponivel")
        current_target = self._target(self.current)
        self._replace_link(self.current, previous_target)
        if current_target is not None:
            self._replace_link(self.previous, current_target)
