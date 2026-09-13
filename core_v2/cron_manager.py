#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import unicodedata
import uuid
from pathlib import Path

ROOT = Path.home() / ".hermes" / "core-v2"
STATE = ROOT / "state"
SCRIPTS = Path.home() / ".hermes" / "scripts"
TASKS_FILE = STATE / "managed_crons.json"
PYTHON = ROOT / "venv" / "bin" / "python"
RUNNER = ROOT / "cron_task_runner.py"
HERMES = "hermes"
RESULT_PREFIX = "HERMES_CRON_RESULT:"

WEEKDAYS = {
    "segunda": "monday",
    "terca": "tuesday",
    "terça": "tuesday",
    "quarta": "wednesday",
    "quinta": "thursday",
    "sexta": "friday",
    "sabado": "saturday",
    "sábado": "saturday",
    "domingo": "sunday",
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def run(args: list[str], timeout: int = 30) -> tuple[int, str]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode, out.strip()


def load_tasks() -> dict:
    STATE.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        return {}
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_tasks(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def time_token(text: str) -> str | None:
    m = re.search(r"(?:as|às|at)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?", norm(text))
    if not m:
        return None
    hh = min(23, int(m.group(1)))
    mm = min(59, int(m.group(2) or 0))
    return f"{hh:02d}:{mm:02d}"


def parse_schedule(text: str) -> str | None:
    t = norm(text)
    clock = time_token(text)

    m = re.search(r"\ba cada\s+(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        suffix = "m" if "minuto" in unit else "h" if "hora" in unit else "d"
        return f"every {n}{suffix}"

    m = re.search(r"\bem\s+(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        suffix = "m" if "minuto" in unit else "h" if "hora" in unit else "d"
        return f"in {n}{suffix}"

    if ("todo dia" in t or "todos os dias" in t or "diariamente" in t) and clock:
        return f"every day at {clock}"
    if ("segunda a sexta" in t or "segunda-feira a sexta-feira" in t or "dias uteis" in t) and clock:
        return f"weekdays at {clock}"
    if ("fim de semana" in t or "finais de semana" in t) and clock:
        return f"weekends at {clock}"

    for pt, en in WEEKDAYS.items():
        if re.search(rf"\b(toda|todo|cada)\s+{re.escape(norm(pt))}\b", t) and clock:
            return f"every {en} at {clock}"

    return None


def extract_topic(text: str) -> tuple[str, str]:
    t = text.strip()
    nt = norm(t)
    if "noticia" in nt:
        m = re.search(r"not[ií]cias?(?:\s+(?:sobre|de|do|da))?\s+(.+)", t, re.IGNORECASE)
        query = (m.group(1) if m else "tecnologia").strip(" .")
        query = re.sub(r"\s+(todo dia|todos os dias|diariamente|às?\s*\d{1,2}.*)$", "", query, flags=re.IGNORECASE).strip()
        return "news", query or "tecnologia"

    cleaned = re.sub(r"^(crie|criar|adicione|adicionar|agende|agendar|me lembre|lembre-me)\s+", "", t, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(todo dia|todos os dias|diariamente|a cada \d+ (?:minutos?|horas?|dias?))\b.*", "", cleaned, flags=re.IGNORECASE).strip(" ,.-")
    return "reminder", cleaned or t


def make_name(kind: str, content: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9À-ÿ ]+", "", content).strip()[:44]
    prefix = "Notícias" if kind == "news" else "Lembrete"
    return f"{prefix} - {stem}" if stem else prefix


def create_job(text: str) -> str:
    schedule = parse_schedule(text)
    if not schedule:
        return "Não consegui identificar o horário/frequência. Exemplo: 'todo dia às 8h me mande notícias de Flutter' ou 'em 30 minutos me lembre de ligar para João'."

    kind, content = extract_topic(text)
    task_id = uuid.uuid4().hex[:12]
    slug = f"managed-{task_id}.sh"
    name = make_name(kind, content)

    tasks = load_tasks()
    tasks[task_id] = {
        "type": kind,
        "message": content if kind == "reminder" else "",
        "query": content if kind == "news" else "",
        "schedule": schedule,
        "name": name,
        "source": "telegram-natural-language",
    }
    save_tasks(tasks)

    SCRIPTS.mkdir(parents=True, exist_ok=True)
    script = SCRIPTS / slug
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'exec "{PYTHON}" "{RUNNER}" "{task_id}"\n',
        encoding="utf-8",
    )
    script.chmod(0o700)

    code, out = run([HERMES, "cron", "create", schedule, "--no-agent", "--script", slug, "--deliver", "telegram", "--name", name])
    if code != 0:
        tasks.pop(task_id, None)
        save_tasks(tasks)
        try:
            script.unlink()
        except Exception:
            pass
        return f"Não consegui criar a rotina. {out[-500:]}"

    job_match = re.search(r"Created job:\s*([^\s]+)", out)
    job_id = job_match.group(1) if job_match else "criado"
    return f"✅ Rotina criada\nNome: {name}\nAgenda: {schedule}\nID: {job_id}\nEntrega: Telegram\nModo: local/no-agent"


def extract_target(text: str, action_words: str) -> str:
    m = re.search(action_words + r"\s+(?:a\s+)?(?:rotina|cron|lembrete)?\s*[\"']?(.+?)[\"']?$", text.strip(), re.IGNORECASE)
    return (m.group(1).strip(" .'\"") if m else "").strip()


def lifecycle(text: str) -> str | None:
    t = norm(text)
    if any(x in t for x in ("quais rotinas", "listar rotinas", "liste as rotinas", "minhas rotinas", "listar crons")):
        code, out = run([HERMES, "cron", "list", "--all"])
        return out if code == 0 else f"Erro ao listar rotinas: {out}"

    operations = [
        (("pause", "parar", "pare", "pausar", "pause"), "pause"),
        (("retome", "retomar", "continuar", "resume"), "resume"),
        (("remova", "remover", "apague", "apagar", "delete"), "remove"),
        (("rode", "rodar", "execute", "executar"), "run"),
    ]
    for words, command in operations:
        if any(t.startswith(w + " ") for w in words):
            target = extract_target(text, r"(?:" + "|".join(words) + r")")
            if not target:
                return "Diga o nome ou ID da rotina que deseja alterar."
            code, out = run([HERMES, "cron", command, target])
            if code != 0:
                return f"Não consegui alterar a rotina '{target}'. {out[-500:]}"
            labels = {"pause": "pausada", "resume": "retomada", "remove": "removida", "run": "executada"}
            return f"✅ Rotina {labels[command]}: {target}"
    return None


def handle(text: str) -> str:
    life = lifecycle(text)
    if life is not None:
        return life
    t = norm(text)
    create_words = ("crie", "criar", "adicione", "adicionar", "agende", "agendar", "me lembre", "lembre-me")
    if any(w in t for w in create_words):
        return create_job(text)
    return "Não identifiquei uma ação de rotina. Posso criar, listar, pausar, retomar, executar ou remover rotinas."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-b64", required=True)
    args = parser.parse_args()
    try:
        text = base64.urlsafe_b64decode(args.text_b64.encode()).decode("utf-8")
    except Exception:
        print(RESULT_PREFIX + "Não consegui interpretar a solicitação.")
        return 2
    result = handle(text)
    print(RESULT_PREFIX + result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
