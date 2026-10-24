#!/usr/bin/env python3
"""Contrato declarativo de ownership do staging da fronteira de deploy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    user: str
    primary_group: str
    supplementary_groups: frozenset[str] = frozenset()

    @property
    def groups(self) -> frozenset[str]:
        return self.supplementary_groups | {self.primary_group}


@dataclass(frozen=True)
class PathContract:
    owner: str
    group: str
    mode: int

    def allows(self, identity: Identity, operation: str) -> bool:
        bit = {"read": 4, "write": 2, "execute": 1}[operation]
        if identity.user == self.owner:
            granted = (self.mode >> 6) & 7
        elif self.group in identity.groups:
            granted = (self.mode >> 3) & 7
        else:
            granted = self.mode & 7
        return bool(granted & bit)


WORKDEV_API = Identity(
    "workdev", "workdev", frozenset({"workdev-runtime"})
)
WORKDEV_AGENT = Identity("workdev", "workdev")
WORKDEV_DEPLOY = Identity(
    "workdev-deploy", "workdev-deploy", frozenset({"workdev-runtime"})
)

RUNTIME = PathContract("workdev-deploy", "workdev-runtime", 0o750)
RELEASES = PathContract("workdev-deploy", "workdev-runtime", 0o750)
RELEASE_DIRECTORY = PathContract("workdev-deploy", "workdev-runtime", 0o750)
RELEASE_FILE = PathContract("workdev-deploy", "workdev-runtime", 0o640)

PATHS = {
    "/opt/workdev": PathContract("workdev", "workdev-runtime", 0o750),
    "/home/workdev": PathContract("workdev", "workdev", 0o700),
    "/home/workdev/.claude": PathContract("workdev", "workdev", 0o700),
    "/home/workdev/.codex": PathContract("workdev", "workdev", 0o700),
    "/home/workdev/.kimi": PathContract("workdev", "workdev", 0o700),
    "/etc/workdev": PathContract("root", "workdev", 0o750),
    "/etc/workdev/workdev-api.env": PathContract("workdev", "workdev", 0o600),
    "/etc/workdev/agents-alert.env": PathContract("workdev", "workdev", 0o600),
    "/var/lib/agents-healthcheck": PathContract("workdev", "workdev", 0o750),
    "/var/lib/workdev-supervisor": PathContract("workdev", "workdev", 0o750),
    "/run/lock/workdev-supervisor.lock": PathContract("workdev", "workdev", 0o640),
    "/opt/workdev/apps/api/venv": PathContract("root", "workdev", 0o750),
    "/var/lib/workdev-deploy": PathContract("workdev-deploy", "workdev-deploy", 0o700),
    "/etc/workdev-deploy": PathContract("root", "workdev-deploy", 0o750),
    "/etc/workdev-deploy/signing.key": PathContract("workdev-deploy", "workdev-deploy", 0o600),
    "/usr/local/lib/workdev-deploy": PathContract("root", "root", 0o755),
    "/usr/local/sbin/workdev-deployctl": PathContract("root", "root", 0o755),
    "/usr/local/libexec/workdev-deploy-readcheck": PathContract("root", "root", 0o755),
}
