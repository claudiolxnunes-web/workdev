#!/usr/bin/env python3
"""Run the existing WorkDev gate under the operational user, then persist it."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID

ROOT = Path('/opt/workdev')


def git(*args):
    result = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def validate_tree(run):
    # Backend evidence currently validates against /opt/workdev, not a worktree.
    # Do not silently test production for a run executing in an isolated tree.
    if git('rev-parse', '--show-toplevel') != str(ROOT):
        raise RuntimeError('Raiz Git inesperada; gate recusado')
    branch = git('branch', '--show-current')
    if run.branch and run.branch != branch:
        raise RuntimeError('Branch da execução difere de /opt/workdev. Use o gate do worker isolado; nenhuma evidência criada.')
    if git('status', '--porcelain'):
        raise RuntimeError('Árvore com alterações ou arquivos não rastreados. Revise e registre somente as alterações da execução antes do gate.')
    return git('rev-parse', 'HEAD')


def run_gate(db, run, execute_gate, persist_gate_evidence, get_gate_evidence_for_run):
    if run.status != 'running':
        raise RuntimeError(f'Gate de entrega exige running; status: {run.status}')
    sha = validate_tree(run)
    evidence = get_gate_evidence_for_run(db, run)
    if evidence and evidence.passed:
        print(f'Gate válido já registrado para o commit {sha}; reutilizado.', flush=True)
        return
    print(f'Executando checks reais para {run.id}, commit {sha}...', flush=True)
    evidence = execute_gate(run)
    if validate_tree(run) != sha or evidence.git_commit_sha != sha:
        raise RuntimeError('Código mudou durante o gate; resultado não registrado. Execute novamente.')
    event = persist_gate_evidence(db, evidence)
    for check in evidence.checks:
        print(f"{check.name}: {'PASS' if check.passed else 'FAIL'} — {check.reason}", flush=True)
    print(f'Evidência registrada: {event.id}', flush=True)
    if not evidence.passed:
        raise RuntimeError(evidence.error or 'Gate reprovado')
    db.refresh(run)
    if run.status != 'running':
        raise RuntimeError('Estado da execução mudou durante os testes; entrega interrompida')
    if not get_gate_evidence_for_run(db, run):
        raise RuntimeError('API não considera a evidência válida; entrega interrompida')
    print('GATE APROVADO', flush=True)


def main():
    if os.geteuid() == 0:
        raise RuntimeError('Gate recusado como root; execute como workdev')
    run_id = UUID(sys.argv[1])
    # Import the same registered model set used by the working manual command.
    from app.routers.handoffs import SessionLocal, AgentRun
    from app.services.test_gate import execute_gate, persist_gate_evidence, get_gate_evidence_for_run
    # Global lock prevents simultaneous gates writing into shared build/cache dirs.
    lock_dir = ROOT / '.workdev' / 'review-gates'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / 'cli-gate.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Outro gate CLI está em execução; tente novamente após terminar')
        with SessionLocal() as db:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is None:
                raise RuntimeError('Execução não encontrada; nenhum teste executado')
            run_gate(db, run, execute_gate, persist_gate_evidence, get_gate_evidence_for_run)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'erro de gate: {error}', file=sys.stderr)
        raise SystemExit(1)
