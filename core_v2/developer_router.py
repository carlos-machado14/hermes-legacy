#!/usr/bin/env python3
from __future__ import annotations

import re

from action_queue import add_action, approve, get_action, update_action
from decision_log import record
from github_workspace import (
    auth_status,
    setup_help,
    list_repos,
    repo_info,
    clone_repo,
    git_status,
    git_diff,
    create_local_branch,
    local_commit,
    execute_github_action,
)


def _after(text: str, markers: tuple[str, ...]) -> str:
    low = text.lower()
    for marker in markers:
        i = low.find(marker)
        if i >= 0:
            return text[i + len(marker):].strip(' :,-')
    return ''


def _fmt_repos(rows: list[dict]) -> str:
    if not rows:
        return 'Nenhum repositório encontrado nessa conta.'
    out = ['Repositórios GitHub recentes:']
    for row in rows[:30]:
        vis = row.get('visibility') or ('PRIVATE' if row.get('isPrivate') else 'PUBLIC')
        out.append(f"- {row.get('nameWithOwner')} | {vis} | {row.get('url')}")
    return '\n'.join(out)


def handle(text: str) -> str | None:
    t = text.strip()
    low = t.lower()

    if low.startswith('aprovar ação ') or low.startswith('aprovar acao '):
        ref = _after(t, ('aprovar ação', 'aprovar acao'))
        action = get_action(ref)
        if action and str(action.get('kind') or '').startswith('github_'):
            try:
                approved = approve(ref)
                update_action(approved['id'], status='running')
                result = execute_github_action(approved)
                update_action(approved['id'], status='done', result=result)
                record('github_action_completed', approved.get('title',''), metadata={'action_id': approved['id'], 'kind': approved.get('kind')})
                return f"Ação GitHub concluída: [{approved['id']}]\n{result}"
            except Exception as exc:
                if action:
                    try: update_action(action['id'], status='failed', error=str(exc))
                    except Exception: pass
                return f'Falha ao executar a ação GitHub aprovada: {exc}'

    if low in {'github', 'status github', 'status do github', 'github status', 'conexão github', 'conexao github'}:
        st = auth_status()
        if st.get('ok'):
            return f"GitHub conectado como {st.get('login') or 'usuário autenticado'}. Workspace local: ~/.hermes/workspaces"
        return setup_help()

    if any(k in low for k in ('meus repositórios', 'meus repositorios', 'listar repositórios', 'listar repositorios', 'repos do github', 'repositórios github', 'repositorios github')):
        try:
            return _fmt_repos(list_repos(30))
        except Exception as exc:
            return f'Não consegui listar os repositórios: {exc}'

    if low.startswith('ver repo ') or low.startswith('ver repositório ') or low.startswith('ver repositorio '):
        repo = _after(t, ('ver repo', 'ver repositório', 'ver repositorio'))
        try:
            info = repo_info(repo)
            branch = ((info.get('defaultBranchRef') or {}).get('name') or '-')
            return (
                f"{info.get('nameWithOwner')}\n"
                f"Visibilidade: {info.get('visibility')}\n"
                f"Branch padrão: {branch}\n"
                f"URL: {info.get('url')}\n"
                f"Descrição: {info.get('description') or '-'}"
            )
        except Exception as exc:
            return f'Não consegui consultar o repositório: {exc}'

    if any(low.startswith(k) for k in ('clone repo ', 'clonar repo ', 'clone repositório ', 'clonar repositório ', 'clone repositorio ', 'clonar repositorio ')):
        repo = _after(t, ('clone repo', 'clonar repo', 'clone repositório', 'clonar repositório', 'clone repositorio', 'clonar repositorio'))
        try:
            result = clone_repo(repo)
            return f"Repositório disponível localmente em {result['path']}" + (' (já estava clonado).' if result.get('already_exists') else '.')
        except Exception as exc:
            return f'Não consegui clonar: {exc}'

    if any(low.startswith(k) for k in ('status git ', 'status do projeto ', 'status projeto ')):
        repo = _after(t, ('status git', 'status do projeto', 'status projeto'))
        return git_status(repo)

    if any(low.startswith(k) for k in ('diff ', 'ver diff ', 'mudanças do projeto ', 'mudancas do projeto ')):
        repo = _after(t, ('ver diff', 'mudanças do projeto', 'mudancas do projeto', 'diff'))
        return git_diff(repo)

    m = re.match(r'^(?:crie|criar|nova)\s+branch\s+([^\s]+)\s+(?:no|na|em)\s+(?:projeto\s+)?(.+)$', t, flags=re.I)
    if m:
        branch, repo = m.group(1).strip(), m.group(2).strip()
        try:
            return create_local_branch(repo, branch)
        except Exception as exc:
            return f'Não consegui criar a branch local: {exc}'

    m = re.match(r'^(?:faça|faca|crie|criar)\s+commit\s+(?:no|na|em)\s+(?:projeto\s+)?([^:]+)(?::\s*(.+))?$', t, flags=re.I)
    if m:
        repo = m.group(1).strip()
        message = (m.group(2) or 'Atualização realizada pelo Hermes').strip()
        try:
            return local_commit(repo, message)
        except Exception as exc:
            return f'Não consegui criar o commit local: {exc}'

    if any(low.startswith(k) for k in ('crie repositório ', 'criar repositório ', 'crie repositorio ', 'criar repositorio ', 'novo repositório ', 'novo repositorio ')):
        name = _after(t, ('crie repositório', 'criar repositório', 'crie repositorio', 'criar repositorio', 'novo repositório', 'novo repositorio'))
        name = name.split()[0] if name else ''
        if not name:
            return 'Informe o nome do repositório.'
        action = add_action(
            f'Criar repositório GitHub {name}',
            kind='github_create_repo', risk='medium', requires_approval=True,
            payload={'name': name, 'private': True, 'source': 'developer_router'},
        )
        record('github_action_proposed', action['title'], metadata={'action_id': action['id']})
        return f"Preparei a criação do repositório privado '{name}'. Para confirmar, use: aprovar ação {action['id']}"

    if any(low.startswith(k) for k in ('push ', 'faça push ', 'faca push ', 'enviar código ', 'enviar codigo ')):
        repo = _after(t, ('faça push', 'faca push', 'enviar código', 'enviar codigo', 'push'))
        if not repo:
            return 'Informe o projeto/repositório para o push.'
        action = add_action(
            f'Push GitHub do projeto {repo}', kind='github_push', risk='medium', requires_approval=True,
            payload={'repo': repo, 'source': 'developer_router'},
        )
        record('github_action_proposed', action['title'], metadata={'action_id': action['id']})
        return f"Push preparado. Como altera o GitHub remoto, preciso da sua aprovação: aprovar ação {action['id']}"

    m = re.match(r'^(?:crie|criar|abra|abrir)\s+(?:um\s+)?pr\s+(?:do|da|no|na|em)\s+(?:projeto\s+)?([^:]+)(?::\s*(.+))?$', t, flags=re.I)
    if m:
        repo = m.group(1).strip()
        title = (m.group(2) or 'Atualização do projeto').strip()
        action = add_action(
            f'Criar PR GitHub do projeto {repo}', kind='github_create_pr', risk='medium', requires_approval=True,
            payload={'repo': repo, 'title': title, 'body': 'PR preparado pelo Hermes após revisão local.', 'base': 'main', 'source': 'developer_router'},
        )
        record('github_action_proposed', action['title'], metadata={'action_id': action['id']})
        return f"PR preparado. Para publicar no GitHub, aprove: aprovar ação {action['id']}"

    return None
