#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import httpx

ROOT = Path.home() / ".hermes" / "core-v2"
STATE = ROOT / "state"
TASKS_FILE = STATE / "managed_crons.json"
UA = "HermesCore/2.0 (+local-first)"
PYTHON = ROOT / "venv" / "bin" / "python"
CORE_ENTRY = ROOT / "core_entry.py"


def load_tasks() -> dict:
    if not TASKS_FILE.exists():
        return {}
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clean(text: str, limit: int = 220) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def run_news(task: dict) -> str:
    query = str(task.get("query") or task.get("message") or "notícias").strip()
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    try:
        with httpx.Client(timeout=12, headers={"User-Agent": UA}, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as exc:
        return f"⚠️ Não consegui coletar notícias sobre {query}: {exc}"

    lines = [f"📰 Notícias sobre {query}", ""]
    count = 0
    for entry in feed.entries[:8]:
        title = clean(getattr(entry, "title", ""), 150)
        link = getattr(entry, "link", "") or ""
        if not title:
            continue
        count += 1
        lines.append(f"{count}. {title}")
        if link:
            lines.append(f"🔗 {link}")
        if count >= 6:
            break
    if count == 0:
        lines.append("Nenhuma notícia encontrada agora.")
    return "\n".join(lines)


def run_agent_task(task: dict) -> str:
    request = str(task.get("message") or "").strip()
    if not request:
        return "⚠️ A rotina de pesquisa está sem instrução."

    prompt = (
        "Execute esta rotina recorrente agora, de forma autônoma e objetiva. "
        "Use pesquisa web/browser/ferramentas locais quando necessário. "
        "Não invente dados: só entregue informações verificáveis. "
        "Se a tarefa pedir contato de empresa, priorize informações públicas da própria empresa ou perfis públicos confiáveis. "
        "Retorne o resultado final pronto para Telegram, sem explicar seu processo interno.\n\n"
        f"TAREFA RECORRENTE:\n{request}"
    )
    try:
        proc = subprocess.run(
            [str(PYTHON), str(CORE_ENTRY), prompt],
            text=True,
            capture_output=True,
            timeout=240,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return "⚠️ A pesquisa excedeu 4 minutos e foi interrompida. Nenhum dado foi inventado."
    except Exception as exc:
        return f"⚠️ Não consegui executar a pesquisa recorrente agora: {exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "erro desconhecido").strip()[-700:]
        return f"⚠️ A rotina falhou antes de concluir: {detail}"
    result = (proc.stdout or "").strip()
    return result or "⚠️ A rotina concluiu sem encontrar um resultado verificável."


def run_task(task: dict) -> str:
    kind = str(task.get("type") or "reminder")
    if kind == "news":
        return run_news(task)
    if kind == "agent_task":
        return run_agent_task(task)
    message = str(task.get("message") or "Lembrete").strip()
    return f"🔔 Lembrete\n{message}"


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: cron_task_runner.py <task_id>", file=sys.stderr)
        return 2
    task_id = sys.argv[1]
    task = load_tasks().get(task_id)
    if not isinstance(task, dict):
        print(f"⚠️ Rotina local não encontrada: {task_id}")
        return 1
    print(run_task(task))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
