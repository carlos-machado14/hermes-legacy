#!/usr/bin/env python3
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'personal_profile.json'


def _load() -> dict[str, Any]:
    try: return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: return {'facts': {}, 'skills': [], 'preferences': {}, 'updated_at': None}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data['updated_at'] = int(time.time())
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def remember_fact(key: str, value: Any) -> dict[str, Any]:
    data = _load(); data.setdefault('facts', {})[key.strip()] = value; _save(data); return data


def add_skill(skill: str) -> dict[str, Any]:
    data = _load(); skills = data.setdefault('skills', [])
    if skill.strip() and skill.strip().casefold() not in [s.casefold() for s in skills]: skills.append(skill.strip())
    _save(data); return data


def set_preference(key: str, value: Any) -> dict[str, Any]:
    data = _load(); data.setdefault('preferences', {})[key.strip()] = value; _save(data); return data


def profile() -> dict[str, Any]: return _load()


def summary() -> str:
    p = _load(); out = ['Perfil pessoal do Hermes:']
    skills = p.get('skills') or []
    if skills: out.append('- Habilidades: ' + ', '.join(skills))
    for k,v in (p.get('facts') or {}).items(): out.append(f'- {k}: {v}')
    for k,v in (p.get('preferences') or {}).items(): out.append(f'- Preferência {k}: {v}')
    if len(out) == 1: return 'Perfil pessoal ainda vazio. Diga, por exemplo: "lembre que eu sei Flutter".'
    return '\n'.join(out)
