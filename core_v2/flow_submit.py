#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os

from job_store import create_job


def submit(text: str) -> str:
    job = create_job(
        text,
        source_platform=os.getenv('HERMES_SOURCE_PLATFORM', ''),
        source_chat_id=os.getenv('HERMES_SOURCE_CHAT_ID', ''),
        source_user_id=os.getenv('HERMES_SOURCE_USER_ID', ''),
    )
    return (
        f"Vou realizar essa tarefa em segundo plano. Assim que finalizar, retorno com o resultado.\n"
        f"Fluxo: {job['id']}\n"
        "Você pode continuar me enviando outras mensagens normalmente."
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--text-b64', required=True)
    args = p.parse_args()
    try:
        text = base64.urlsafe_b64decode(args.text_b64.encode()).decode('utf-8')
    except Exception:
        print('Não consegui interpretar a tarefa.')
        return 2
    print(submit(text))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
