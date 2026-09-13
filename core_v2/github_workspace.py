#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

WORKSPACES = Path.home() / '.hermes' / 'workspaces'


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)


def gh_available() -> bool:
    return shutil.which('gh') is not None


def git_available() -> bool:
    return shutil.which('git') is not None


def auth_status() -> dict[str, Any]:
    if not gh_available():
        return {'ok': False, 'reason': 'gh_missing', 'message': 'GitHub CLI (gh) não está instalada.'}
    p = _run(['gh', 'auth', 'status'], timeout=15)
    if p.returncode != 0:
        return {'ok': False, 'reason': 'not_authenticated', 'message': (p.stderr or p.stdout).strip()[-1200:]}
    user = _run(['gh', 'api', 'user', '--jq', '.login'], timeout=15)
    login = user.stdout.strip() if user.returncode == 0 else ''
    return {'ok': True, 'login': login, 'message': 'GitHub conectado.'}


def setup_help() -> str:
    status = auth_status()
    if status.get('ok'):
        return f"GitHub conectado como {status.get('login') or 'usuário autenticado'}."
    if status.get('reason') == 'gh_missing':
        return 'GitHub CLI ainda não está instalada. Na VPS, instale com: sudo apt-get update && sudo apt-get install -y gh'
    return 'GitHub CLI instalada, mas falta autenticar. Na VPS, execute: gh auth login'


def _safe_repo(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?', value):
        raise ValueError('nome de repositório inválido')
    return value


def _safe_branch(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', value) or '..' in value or value.startswith('/') or value.endswith('/'):
        raise ValueError('nome de branch inválido')
    return value


def _workspace_name(repo: str) -> str:
    return repo.split('/')[-1]


def workspace_path(repo_or_name: str) -> Path:
    return WORKSPACES / _workspace_name(repo_or_name)


def list_repos(limit: int = 30) -> list[dict[str, Any]]:
    status = auth_status()
    if not status.get('ok'):
        raise RuntimeError(setup_help())
    p = _run([
        'gh', 'repo', 'list', '--limit', str(max(1, min(limit, 100))),
        '--json', 'nameWithOwner,url,visibility,updatedAt,isPrivate'
    ], timeout=30)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return json.loads(p.stdout or '[]')


def repo_info(repo: str) -> dict[str, Any]:
    repo = _safe_repo(repo)
    p = _run(['gh', 'repo', 'view', repo, '--json', 'nameWithOwner,url,description,defaultBranchRef,visibility,isPrivate'], timeout=20)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return json.loads(p.stdout or '{}')


def clone_repo(repo: str) -> dict[str, Any]:
    repo = _safe_repo(repo)
    if not auth_status().get('ok'):
        raise RuntimeError(setup_help())
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    target = workspace_path(repo)
    if (target / '.git').exists():
        return {'ok': True, 'repo': repo, 'path': str(target), 'already_exists': True}
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f'workspace já existe e não está vazio: {target}')
    p = _run(['gh', 'repo', 'clone', repo, str(target)], timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return {'ok': True, 'repo': repo, 'path': str(target), 'already_exists': False}


def git_status(repo_or_name: str) -> str:
    target = workspace_path(repo_or_name)
    if not (target / '.git').exists():
        return f'Projeto não clonado em {target}.'
    p = _run(['git', 'status', '--short', '--branch'], cwd=target, timeout=15)
    return (p.stdout or p.stderr).strip() or 'Workspace limpo.'


def git_diff(repo_or_name: str, max_chars: int = 6000) -> str:
    target = workspace_path(repo_or_name)
    if not (target / '.git').exists():
        return f'Projeto não clonado em {target}.'
    p = _run(['git', 'diff', '--stat'], cwd=target, timeout=15)
    stat = (p.stdout or '').strip()
    q = _run(['git', 'diff'], cwd=target, timeout=20)
    diff = (q.stdout or q.stderr).strip()
    if len(diff) > max_chars:
        diff = diff[:max_chars] + '\n… diff truncado para conversa.'
    return (stat + '\n\n' + diff).strip() or 'Nenhuma alteração local.'


def create_local_branch(repo_or_name: str, branch: str) -> str:
    target = workspace_path(repo_or_name)
    branch = _safe_branch(branch)
    if not (target / '.git').exists():
        raise RuntimeError(f'Projeto não clonado em {target}.')
    p = _run(['git', 'switch', '-c', branch], cwd=target, timeout=20)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return f'Branch local criada: {branch} em {target.name}'


def local_commit(repo_or_name: str, message: str) -> str:
    target = workspace_path(repo_or_name)
    if not (target / '.git').exists():
        raise RuntimeError(f'Projeto não clonado em {target}.')
    message = message.strip()[:180]
    if not message:
        raise ValueError('mensagem de commit vazia')
    add = _run(['git', 'add', '-A'], cwd=target, timeout=20)
    if add.returncode != 0:
        raise RuntimeError((add.stderr or add.stdout).strip())
    p = _run(['git', 'commit', '-m', message], cwd=target, timeout=30)
    if p.returncode != 0:
        text = (p.stderr or p.stdout).strip()
        if 'nothing to commit' in text.lower() or 'nada para' in text.lower():
            return 'Nenhuma alteração para commit.'
        raise RuntimeError(text)
    return (p.stdout or '').strip()


def create_remote_repo(name: str, *, private: bool = True) -> dict[str, Any]:
    name = _safe_repo(name)
    if '/' in name:
        raise ValueError('para criar um repositório, informe apenas o nome; a conta autenticada será usada')
    status = auth_status()
    if not status.get('ok'):
        raise RuntimeError(setup_help())
    args = ['gh', 'repo', 'create', name, '--private' if private else '--public']
    p = _run(args, timeout=45)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    owner = status.get('login') or ''
    full = f'{owner}/{name}' if owner else name
    return {'ok': True, 'repo': full, 'url': (p.stdout or '').strip()}


def push_workspace(repo_or_name: str, *, set_upstream: bool = True) -> str:
    target = workspace_path(repo_or_name)
    if not (target / '.git').exists():
        raise RuntimeError(f'Projeto não clonado em {target}.')
    branch_p = _run(['git', 'branch', '--show-current'], cwd=target, timeout=10)
    branch = branch_p.stdout.strip()
    if not branch:
        raise RuntimeError('não foi possível determinar a branch atual')
    args = ['git', 'push']
    if set_upstream:
        args += ['-u', 'origin', branch]
    p = _run(args, cwd=target, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return (p.stdout or p.stderr).strip() or f'Push concluído para {branch}.'


def create_pr(repo_or_name: str, *, title: str, body: str = '', base: str = 'main') -> str:
    target = workspace_path(repo_or_name)
    if not (target / '.git').exists():
        raise RuntimeError(f'Projeto não clonado em {target}.')
    title = title.strip()[:180]
    if not title:
        raise ValueError('título do PR vazio')
    p = _run(['gh', 'pr', 'create', '--title', title, '--body', body[:4000], '--base', _safe_branch(base)], cwd=target, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return (p.stdout or '').strip()


def execute_github_action(action: dict[str, Any]) -> str:
    kind = str(action.get('kind') or '')
    payload = dict(action.get('payload') or {})
    if kind == 'github_create_repo':
        result = create_remote_repo(str(payload.get('name') or ''), private=bool(payload.get('private', True)))
        return f"Repositório criado: {result.get('repo')}\n{result.get('url') or ''}".strip()
    if kind == 'github_push':
        return push_workspace(str(payload.get('repo') or ''))
    if kind == 'github_create_pr':
        return create_pr(str(payload.get('repo') or ''), title=str(payload.get('title') or 'Atualização'), body=str(payload.get('body') or ''), base=str(payload.get('base') or 'main'))
    raise ValueError(f'ação GitHub não suportada: {kind}')
