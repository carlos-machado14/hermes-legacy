#!/usr/bin/env python3
from __future__ import annotations

import json, time, uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

from research_engine import web_search

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'research_reports.json'


def _read_page(url: str, max_chars: int = 6000) -> str:
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers={'User-Agent':'Mozilla/5.0 Hermes-Core/3.5'}) as c:
            r=c.get(url); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        for tag in soup(['script','style','noscript']): tag.decompose()
        return ' '.join(soup.get_text(' ',strip=True).split())[:max_chars]
    except Exception:
        return ''


def research(query: str, limit: int = 6) -> dict:
    rows=web_search(query, limit=max(3,min(limit,8)))
    seen=set(); sources=[]
    for row in rows:
        url=row.get('url','')
        host=urlparse(url).netloc.lower()
        if not url or host in seen: continue
        seen.add(host)
        text=_read_page(url)
        sources.append({'title':row.get('title',''),'url':url,'snippet':row.get('snippet',''),'content':text[:3500]})
    report={'id':uuid.uuid4().hex[:10],'query':query,'created_at':int(time.time()),'sources':sources}
    try:
        data=json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: data={'reports':[]}
    data.setdefault('reports',[]).append(report); data['reports']=data['reports'][-100:]
    STATE_DIR.mkdir(parents=True,exist_ok=True); FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def format_report(query: str) -> str:
    report=research(query)
    if not report['sources']: return 'Não encontrei fontes suficientes para a pesquisa.'
    out=[f"Pesquisa aprofundada: {query}", f"Fontes analisadas: {len(report['sources'])}"]
    for i,s in enumerate(report['sources'],1):
        excerpt=(s.get('content') or s.get('snippet') or '')[:500]
        out.append(f"\n{i}. {s.get('title')}\n{excerpt}\n{s.get('url')}")
    out.append(f"\nRelatório salvo: {report['id']}")
    return '\n'.join(out)
