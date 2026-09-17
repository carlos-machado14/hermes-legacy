from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import defaultdict
from typing import Any

from daily_agent_examples import EXAMPLES
from telemetry import emit

_ACTION = {'list':'L','create':'C','remove':'R','update':'U','pause':'P','resume':'V','run':'X','complete':'D','reschedule':'G','answer':'N','search':'H','status':'S','none':'N'}
_ENTITY = {'day':'A','reminder':'M','alert':'L','event':'E','commitment':'C','routine':'R','task':'T','schedule':'S','automation':'S','unknown':'O'}
_SCOPE = {'single':'1','all':'A','filtered':'F','selection':'P','unknown':'U'}
_MODE = {'query':'Q','action':'A','followup':'F','chat':'C'}
_ROUTE = {'time':'T','task':'K','automation':'U','assistant':'S','research':'W','developer':'D','devops':'O','memory':'M','finance':'F','chat':'C','connected':'S','mission':'S'}
_MUTATING_CODES = {'C','R','U','P','V','X','D','G'}
_SAFE_FALLBACK = 'N|O|U|C|S'

# Corpus de treino adicional. São exemplos de linguagem, não comandos nem roteamento por frase.
# O classificador aprende similaridade de palavras + n-grams de caracteres e agrupa por intenção.
_EXTRA_EXAMPLES: list[dict[str, Any]] = [
    {'u':'limpa minha agenda inteira e cancela tudo que está marcado', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'apaga todos os compromissos e deixa minha agenda vazia', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'quero zerar tudo que tenho agendado', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'cancela todos os compromissos da minha agenda', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'remove tudo da agenda', 'o':{'mode':'action','route':'time','action':'remove','entity':'schedule','scope':'all'}},
    {'u':'quais são as minhas rotinas', 'o':{'mode':'query','route':'automation','action':'list','entity':'routine','scope':'all'}},
    {'u':'lista todas as rotinas que tenho', 'o':{'mode':'query','route':'automation','action':'list','entity':'routine','scope':'all'}},
    {'u':'qual é minha agenda para sábado', 'o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'o que tenho marcado no sábado', 'o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'me lembra amanhã às dez de revisar o hermes', 'o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
]


def _label(item: dict[str, Any]) -> str:
    out = item.get('o') if isinstance(item.get('o'), dict) else {}
    return '|'.join([
        _ACTION.get(str(out.get('action') or 'none'), 'N'),
        _ENTITY.get(str(out.get('entity') or 'unknown'), 'O'),
        _SCOPE.get(str(out.get('scope') or 'unknown'), 'U'),
        _MODE.get(str(out.get('mode') or 'chat'), 'C'),
        _ROUTE.get(str(out.get('route') or 'assistant'), 'S'),
    ])


def _normalize(text: str) -> str:
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _features(text: str) -> dict[str, float]:
    value = _normalize(text)
    words = value.split()
    feats: dict[str, float] = defaultdict(float)

    # Palavras e bigramas preservam intenção e objeto.
    for word in words:
        if len(word) > 1:
            feats['w:' + word] += 2.4
    for i in range(len(words) - 1):
        feats['b:' + words[i] + '_' + words[i + 1]] += 3.0

    # N-grams de caracteres dão robustez a flexões, abreviações e pequenos erros de digitação.
    compact = '^' + value.replace(' ', '_') + '$'
    for n, weight in ((3, 0.45), (4, 0.7), (5, 0.9)):
        for i in range(max(0, len(compact) - n + 1)):
            feats[f'c{n}:' + compact[i:i+n]] += weight
    return dict(feats)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    if dot <= 0:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / max(1e-9, na * nb)


_CORPUS = [*_EXTRA_EXAMPLES, *EXAMPLES]
_TRAINING = [(_features(str(item.get('u') or '')), _label(item), str(item.get('u') or '')) for item in _CORPUS]


def _rank(text: str) -> list[tuple[float, str, str]]:
    q = _features(text)
    by_label: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for feats, label, sample in _TRAINING:
        score = _cosine(q, feats)
        by_label[label].append((score, sample))

    ranked: list[tuple[float, str, str]] = []
    for label, scores in by_label.items():
        scores.sort(reverse=True, key=lambda row: row[0])
        # O melhor exemplo domina; os seguintes da mesma intenção reforçam sem esmagar outras classes.
        combined = scores[0][0]
        if len(scores) > 1:
            combined += scores[1][0] * 0.18
        if len(scores) > 2:
            combined += scores[2][0] * 0.07
        ranked.append((combined, label, scores[0][1]))
    ranked.sort(reverse=True, key=lambda row: row[0])
    return ranked


def classify(text: str, recent_context: str = '') -> str:
    started = time.perf_counter()
    current = re.sub(r'\s+', ' ', str(text or '')).strip()[:700]
    if not current:
        return _SAFE_FALLBACK

    ranked = _rank(current)
    if not ranked:
        return _SAFE_FALLBACK

    best_score, best_label, best_sample = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    # Para mutações, em caso de dúvida o sistema NÃO executa. Isso preserva segurança sem
    # obrigar o usuário a falar comandos rígidos quando a intenção está clara.
    if best_label[:1] in _MUTATING_CODES and (best_score < 0.30 or margin < 0.035):
        result = _SAFE_FALLBACK
        guarded = True
    elif best_score < 0.16:
        result = _SAFE_FALLBACK
        guarded = True
    else:
        result = best_label
        guarded = False

    elapsed_ms = (time.perf_counter() - started) * 1000
    emit(
        'brain.provider',
        ok=True,
        provider='local_semantic_classifier',
        model='char_word_ngram_centroid',
        elapsed_ms=elapsed_ms,
        mode='ngram_centroid_v1',
        score=round(best_score, 4),
        margin=round(margin, 4),
        guarded=guarded,
        nearest_example=best_sample[:180],
        output_chars=len(result),
    )
    return result


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    return classify(prompt, '')


def health() -> dict[str, Any]:
    return {
        'primary': {
            'base_url': None,
            'model': 'char_word_ngram_centroid',
            'kind': 'local_semantic_classifier',
        },
        'fallback': None,
        'remote_enabled': False,
        'classifier': 'local_ngram_centroid_v1',
        'circuit_open': False,
        'state': {},
        'timeout_seconds': 0.0,
        'training_examples': len(_TRAINING),
        'generative_model_required': False,
    }
