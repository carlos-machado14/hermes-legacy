#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.home() / '.hermes' / 'core-v2'
HOST = os.getenv('HERMES_OPENAI_BRIDGE_HOST', '127.0.0.1')
PORT = int(os.getenv('HERMES_OPENAI_BRIDGE_PORT', '8091'))
TOKEN = os.getenv('HERMES_CORE_API_TOKEN', '').strip()
MODEL = os.getenv('HERMES_OPENAI_MODEL', 'hermes-agent')


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not TOKEN:
        return True
    return handler.headers.get('Authorization', '') == f'Bearer {TOKEN}'


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get('Content-Length', '0') or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(min(length, 2 * 1024 * 1024)).decode('utf-8'))


def _user_prompt(messages: list[dict]) -> str:
    # O Core ja mantem memoria/conversa. Preservamos a conversa recebida apenas como
    # contexto adicional, priorizando a ultima mensagem do usuario.
    clean: list[str] = []
    for msg in messages[-12:]:
        role = str(msg.get('role') or '')
        content = msg.get('content')
        if not isinstance(content, str) or not content.strip():
            continue
        if role in {'user', 'assistant'}:
            clean.append(f'{role.upper()}: {content.strip()}')
    if not clean:
        return ''
    last_user = next((str(m.get('content')).strip() for m in reversed(messages) if m.get('role') == 'user' and isinstance(m.get('content'), str)), '')
    if len(clean) <= 2:
        return last_user or clean[-1]
    history = '\n'.join(clean[:-1])[-5000:]
    return f'CONTEXTO DO CLIENTE\n{history}\n\nMENSAGEM ATUAL\n{last_user}'


def _run_core(prompt: str) -> str:
    py = ROOT / 'venv' / 'bin' / 'python'
    entry = ROOT / 'core_entry.py'
    proc = subprocess.run(
        [str(py), str(entry), prompt],
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or 'Hermes Core falhou')[-1200:])
    return (proc.stdout or '').strip() or 'Hermes concluiu sem mensagem.'


def _completion_payload(content: str, request_id: str) -> dict:
    return {
        'id': request_id,
        'object': 'chat.completion',
        'created': int(time.time()),
        'model': MODEL,
        'choices': [
            {
                'index': 0,
                'message': {'role': 'assistant', 'content': content},
                'finish_reason': 'stop',
            }
        ],
        'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
    }


def _stream(handler: BaseHTTPRequestHandler, content: str, request_id: str) -> None:
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'keep-alive')
    handler.end_headers()

    # Compatibilidade SSE OpenAI. O Core ainda gera a resposta localmente antes de
    # enviarmos os chunks; a camada de voz pode consumir os blocos imediatamente.
    words = content.split(' ')
    chunks: list[str] = []
    current = ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if len(candidate) >= 120 and current:
            chunks.append(current + ' ')
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)

    first = {
        'id': request_id,
        'object': 'chat.completion.chunk',
        'created': int(time.time()),
        'model': MODEL,
        'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}],
    }
    handler.wfile.write(f"data: {json.dumps(first, ensure_ascii=False)}\n\n".encode('utf-8'))
    handler.wfile.flush()

    for chunk in chunks:
        payload = {
            'id': request_id,
            'object': 'chat.completion.chunk',
            'created': int(time.time()),
            'model': MODEL,
            'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}],
        }
        handler.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode('utf-8'))
        handler.wfile.flush()

    final = {
        'id': request_id,
        'object': 'chat.completion.chunk',
        'created': int(time.time()),
        'model': MODEL,
        'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
    }
    handler.wfile.write(f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode('utf-8'))
    handler.wfile.write(b'data: [DONE]\n\n')
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = 'HermesOpenAIBridge/1.0'

    def log_message(self, fmt: str, *args) -> None:
        return

    def _guard(self) -> bool:
        if _auth_ok(self):
            return True
        _json(self, 401, {'error': {'message': 'unauthorized', 'type': 'auth_error'}})
        return False

    def do_GET(self) -> None:
        if not self._guard():
            return
        path = urlparse(self.path).path
        if path in {'/health', '/v1/health'}:
            _json(self, 200, {'ok': True, 'service': 'hermes-openai-bridge', 'model': MODEL})
        elif path in {'/models', '/v1/models'}:
            _json(self, 200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'hermes'}]})
        elif path in {'/capabilities', '/v1/capabilities'}:
            _json(self, 200, {
                'agent_runtime': True,
                'memory': True,
                'goals': True,
                'tools': True,
                'approvals': True,
                'github': True,
                'voice_ready': True,
                'protocol': 'openai-compatible',
            })
        else:
            _json(self, 404, {'error': {'message': 'not_found'}})

    def do_POST(self) -> None:
        if not self._guard():
            return
        path = urlparse(self.path).path
        if path not in {'/chat/completions', '/v1/chat/completions'}:
            _json(self, 404, {'error': {'message': 'not_found'}})
            return
        try:
            body = _read_json(self)
            messages = list(body.get('messages') or [])
            prompt = _user_prompt(messages)
            if not prompt:
                _json(self, 400, {'error': {'message': 'user_message_required'}})
                return
            content = _run_core(prompt)
            request_id = f'chatcmpl-{uuid.uuid4().hex[:20]}'
            if bool(body.get('stream')):
                _stream(self, content, request_id)
            else:
                _json(self, 200, _completion_payload(content, request_id))
        except subprocess.TimeoutExpired:
            _json(self, 504, {'error': {'message': 'core_timeout', 'type': 'timeout_error'}})
        except Exception as exc:
            _json(self, 502, {'error': {'message': str(exc), 'type': 'hermes_error'}})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Hermes OpenAI Bridge listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
