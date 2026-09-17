from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

from daily_agent_examples import EXAMPLES
from telemetry import emit

_STATE = Path(__file__).resolve().parent / 'state' / 'daily_agent_health.json'
_ENV_FILES = [Path.home() / '.config' / 'hermes' / 'daily-agent.env', Path.home() / '.hermes' / '.env']
_DEFAULT_BASE_URL = 'http://127.0.0.1:8087/v1'
_DEFAULT_MODEL = 'Qwen3-0.6B-Q4_0.gguf'

_ACTION = {'list':'L','create':'C','remove':'R','update':'U','pause':'P','resume':'V','run':'X','complete':'D','reschedule':'G','answer':'N','search':'H','status':'S','none':'N'}
_ENTITY = {'day':'A','reminder':'M','alert':'L','event':'E','commitment':'C','routine':'R','task':'T','schedule':'S','automation':'S','unknown':'O'}
_SCOPE = {'single':'1','all':'A','filtered':'F','selection':'P','unknown':'U'}
_MODE = {'query':'Q','action':'A','followup':'F','chat':'C'}
_ROUTE = {'time':'T','task':'K','automation':'U','assistant':'S','research':'W','developer':'D','devops':'O','memory':'M','finance':'F','chat':'C','connected':'S','mission':'S'}
_MUTATING_ACTIONS = {'create','remove','update','pause','resume','run','complete','reschedule'}

_ACTION_PT = {
    'create': 'criar', 'remove': 'cancelar/remover', 'update': 'alterar', 'pause': 'pausar',
    'resume': 'retomar', 'run': 'executar agora', 'complete': 'concluir', 'reschedule': 'reagendar',
    'list': 'consultar/listar', 'status': 'consultar status', 'answer': 'responder', 'search': 'buscar',
}
_ENTITY_PT = {
    'day': 'agenda de um dia/período', 'reminder': 'lembrete', 'alert': 'alerta', 'event': 'evento',
    'commitment': 'compromisso', 'routine': 'rotina', 'task': 'tarefa', 'schedule': 'agenda inteira / qualquer item agendado',
    'automation': 'automação', 'unknown': 'item não especificado',
}
_SCOPE_PT = {
    'single': 'um item específico', 'all': 'todos os itens desse alvo', 'filtered': 'itens filtrados pela descrição/data',
    'selection': 'itens já selecionados no contexto', 'unknown': 'abrangência não definida',
}

_RERANK_SYSTEM = '''/no_think
Você recebe UMA mensagem atual em português e opções de intenção com exemplos.
Classifique SOMENTE a mensagem atual. Não herde a ação de mensagens anteriores.
Escolha SOMENTE o número da opção que representa melhor o significado da mensagem atual.
Dê prioridade à intenção descrita, depois à frase de exemplo. Considere ação, objeto, pergunta/ordem e singular/plural. Não explique.'''

_VERIFY_SYSTEM = '''/no_think
Você está validando uma ação que pode alterar dados.
A ação principal já foi identificada. Sua única tarefa agora é escolher o ALVO e a ABRANGÊNCIA corretos da mensagem atual.
Diferencie com cuidado: agenda inteira versus lembretes; todos versus um item versus filtro específico.
Escolha SOMENTE o número da opção correta. Não explique.'''

_INDEX_GRAMMAR = 'root ::= "0" | "1" | "2" | "3" | "4" | "5"'

# Exemplos canônicos extras para intenções importantes. Eles entram no mesmo ranking
# semântico do corpus e nunca funcionam como roteamento por frase exata.
_ANCHORS: list[dict[str, Any]] = [
    {'u':'limpa minha agenda inteira e cancela tudo que está marcado', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'apaga todos os compromissos e deixa minha agenda vazia', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'quero zerar tudo que tenho agendado', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'qual é minha agenda para um dia específico', 'o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'me lembra em um dia e horário de fazer alguma coisa', 'o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
]


def _env(name: str) -> str:
    direct = str(os.getenv(name) or '').strip()
    if direct:
        return direct
    for path in _ENV_FILES:
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                raw = line.strip()
                if not raw or raw.startswith('#') or '=' not in raw:
                    continue
                key, value = raw.split('=', 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except Exception:
            continue
    return ''


def _provider() -> tuple[str, str, str | None, str]:
    base_url = (_env('HERMES_DAILY_AGENT_BASE_URL') or _DEFAULT_BASE_URL).rstrip('/')
    model = _env('HERMES_DAILY_AGENT_MODEL') or _DEFAULT_MODEL
    return base_url, model, None, 'daily_agent_local'


def _read_health() -> dict[str, Any]:
    try:
        data = json.loads(_STATE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_health(data: dict[str, Any]) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.replace(_STATE)
    except Exception:
        pass


def _circuit_open() -> bool:
    return float(_read_health().get('open_until') or 0) > time.time()


def _mark_success(elapsed_ms: float) -> None:
    _write_health({'failures': 0, 'open_until': 0, 'last_ok_at': int(time.time()), 'elapsed_ms': round(elapsed_ms, 1)})


def _mark_failure(error: str) -> None:
    state = _read_health()
    failures = int(state.get('failures') or 0) + 1
    cooldown = 5 if failures >= 3 else 0
    _write_health({'failures': failures, 'open_until': int(time.time()) + cooldown if cooldown else 0, 'last_error_at': int(time.time()), 'error': error[:300]})


def _timeout_seconds() -> float:
    return max(2.0, min(10.0, float(_env('HERMES_DAILY_AGENT_TIMEOUT') or 6.0)))


def _norm(text: str) -> tuple[str, set[str]]:
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    clean = ' '.join(re.findall(r'[a-z0-9]+', value))
    return clean, {p for p in clean.split() if len(p) > 1}


def _score_candidate(query: str, qtokens: set[str], item: dict[str, Any]) -> float:
    sample, stokens = _norm(item.get('u') or '')
    overlap = len(qtokens & stokens)
    union = max(1, len(qtokens | stokens))
    lexical = overlap / union
    sequence = SequenceMatcher(None, query, sample).ratio()
    return lexical * 0.65 + sequence * 0.35 + min(overlap, 3) * 0.04


def _signature(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    out = item.get('o') if isinstance(item.get('o'), dict) else {}
    return (
        str(out.get('mode') or 'chat'), str(out.get('route') or 'assistant'), str(out.get('action') or 'none'),
        str(out.get('entity') or 'unknown'), str(out.get('scope') or 'unknown'),
    )


def _ranked_pool(text: str) -> list[tuple[float, int, dict[str, Any]]]:
    query, qtokens = _norm(text)
    pool = [*_ANCHORS, *EXAMPLES]
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for idx, item in enumerate(pool):
        ranked.append((_score_candidate(query, qtokens, item), -idx, item))
    ranked.sort(reverse=True, key=lambda row: (row[0], row[1]))
    return ranked


def _candidates(text: str, limit: int = 6) -> list[dict[str, Any]]:
    # Uma opção por assinatura evita gastar as seis vagas com paráfrases da mesma intenção.
    chosen: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for _score, _idx, item in _ranked_pool(text):
        sig = _signature(item)
        if sig in seen:
            continue
        seen.add(sig)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def _mutation_candidates(text: str, action: str, limit: int = 6) -> list[dict[str, Any]]:
    # Segunda passagem para mutações: mantém a ação fixa e compara apenas alvo+escopo.
    # Isso impede que uma escolha próxima lexicalmente (ex.: "lembrete") transforme
    # "zerar a agenda" em remoção de um subconjunto.
    chosen: list[dict[str, Any]] = []
    seen_target: set[tuple[str, str]] = set()
    for _score, _idx, item in _ranked_pool(text):
        out = item.get('o') if isinstance(item.get('o'), dict) else {}
        if str(out.get('action') or 'none') != action:
            continue
        target_sig = (str(out.get('entity') or 'unknown'), str(out.get('scope') or 'unknown'))
        if target_sig in seen_target:
            continue
        seen_target.add(target_sig)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def _to_label(item: dict[str, Any]) -> str:
    out = item.get('o') if isinstance(item.get('o'), dict) else {}
    return '|'.join([
        _ACTION.get(str(out.get('action') or 'none'), 'N'),
        _ENTITY.get(str(out.get('entity') or 'unknown'), 'O'),
        _SCOPE.get(str(out.get('scope') or 'unknown'), 'U'),
        _MODE.get(str(out.get('mode') or 'chat'), 'C'),
        _ROUTE.get(str(out.get('route') or 'assistant'), 'S'),
    ])


def _intent_hint(item: dict[str, Any]) -> str:
    out = item.get('o') if isinstance(item.get('o'), dict) else {}
    action = str(out.get('action') or 'none')
    entity = str(out.get('entity') or 'unknown')
    scope = str(out.get('scope') or 'unknown')
    mode = str(out.get('mode') or 'chat')
    route = str(out.get('route') or 'assistant')
    return f'{mode}; {action}; {entity}; escopo {scope}; domínio {route}'


def _target_hint(item: dict[str, Any]) -> str:
    out = item.get('o') if isinstance(item.get('o'), dict) else {}
    action = str(out.get('action') or 'none')
    entity = str(out.get('entity') or 'unknown')
    scope = str(out.get('scope') or 'unknown')
    return f'ação={_ACTION_PT.get(action, action)}; alvo={_ENTITY_PT.get(entity, entity)}; abrangência={_SCOPE_PT.get(scope, scope)}'


def _choose_index(base_url: str, model: str, system: str, prompt: str, timeout_seconds: float) -> tuple[int, float]:
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'max_tokens': 2,
        'grammar': _INDEX_GRAMMAR,
        'chat_template_kwargs': {'enable_thinking': False},
    }
    timeout = httpx.Timeout(connect=1.0, read=timeout_seconds, write=timeout_seconds, pool=1.0)
    started = time.perf_counter()
    with httpx.Client(timeout=timeout, headers={'Content-Type': 'application/json'}) as client:
        response = client.post(f'{base_url}/chat/completions', json=payload)
        response.raise_for_status()
        data = response.json()
    message = ((data.get('choices') or [{}])[0].get('message') or {})
    raw = str(message.get('content') or '').strip()
    if not re.fullmatch(r'[0-5]', raw):
        raise RuntimeError(f'daily reranker invalid index: {raw[:40]}')
    return int(raw), (time.perf_counter() - started) * 1000


def classify(text: str, recent_context: str = '') -> str:
    if _circuit_open():
        raise TimeoutError('daily local semantic agent circuit open')

    base_url, model, _key, provider_kind = _provider()
    current = re.sub(r'\s+', ' ', str(text or '')).strip()[:700]
    candidates = _candidates(current, 6)
    if not candidates:
        raise RuntimeError('daily classifier has no semantic candidates')

    options = '\n'.join(
        f'{idx}: intenção={_intent_hint(item)} | exemplo={item["u"]}'
        for idx, item in enumerate(candidates)
    )
    prompt = f'/no_think\nMensagem atual: {current}\nOpções:\n{options}\nNúmero:'
    timeout_seconds = _timeout_seconds()
    total_started = time.perf_counter()
    try:
        index, first_ms = _choose_index(base_url, model, _RERANK_SYSTEM, prompt, timeout_seconds)
        if index >= len(candidates):
            raise RuntimeError(f'daily reranker index out of range: {index}')
        selected = candidates[index]
        selected_out = selected.get('o') if isinstance(selected.get('o'), dict) else {}
        selected_action = str(selected_out.get('action') or 'none')
        verifier_ms = 0.0
        verified = False

        # Mutações merecem uma segunda decisão curta e independente focada somente em alvo+escopo.
        # O Qwen continua decidindo semanticamente; não existe frase/regex especial para "resetar".
        if selected_action in _MUTATING_ACTIONS:
            mutation_options = _mutation_candidates(current, selected_action, 6)
            if len(mutation_options) > 1:
                target_options = '\n'.join(
                    f'{idx}: {_target_hint(item)} | exemplo={item["u"]}'
                    for idx, item in enumerate(mutation_options)
                )
                verify_prompt = (
                    f'/no_think\nMensagem atual: {current}\n'
                    f'Ação principal: {_ACTION_PT.get(selected_action, selected_action)}\n'
                    f'Escolha alvo e abrangência:\n{target_options}\nNúmero:'
                )
                verify_index, verifier_ms = _choose_index(base_url, model, _VERIFY_SYSTEM, verify_prompt, timeout_seconds)
                if verify_index >= len(mutation_options):
                    raise RuntimeError(f'daily mutation verifier index out of range: {verify_index}')
                selected = mutation_options[verify_index]
                verified = True

        result = _to_label(selected)
        elapsed_ms = (time.perf_counter() - total_started) * 1000
        _mark_success(elapsed_ms)
        emit(
            'brain.provider', ok=True, provider=provider_kind, model=model, elapsed_ms=elapsed_ms,
            prompt_chars=len(prompt), output_chars=len(result), mode='example_reranker_v5', selected=index,
            mutation_verified=verified, first_pass_ms=round(first_ms, 1), verifier_ms=round(verifier_ms, 1),
        )
        return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - total_started) * 1000
        _mark_failure(str(exc))
        emit('brain.provider', ok=False, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, error=str(exc)[:300], mode='example_reranker_v5')
        raise


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    return classify(prompt, '')


def health() -> dict[str, Any]:
    primary = _provider()
    return {
        'primary': {'base_url': primary[0], 'model': primary[1], 'kind': primary[3]},
        'fallback': None,
        'remote_enabled': False,
        'classifier': 'semantic_example_reranker_v5_mutation_verifier',
        'circuit_open': _circuit_open(),
        'state': _read_health(),
        'timeout_seconds': _timeout_seconds(),
    }
