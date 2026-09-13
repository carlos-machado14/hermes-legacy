#!/usr/bin/env python3
from __future__ import annotations

import re
from urllib.parse import urlparse

from research_engine import web_search
from lead_manager import add_lead
from opportunity_engine import add as add_opportunity


def _score(title: str, snippet: str) -> int:
    text=(title+' '+snippet).casefold(); score=45
    for k,w in [('site',8),('website',8),('wordpress',6),('instagram',3),('contato',3),('empresa',4),('clínica',5),('advocacia',5),('restaurante',4),('automação',6),('app',5)]:
        if k in text: score += w
    return max(0,min(100,score))


def hunt(query: str, limit: int = 10) -> list[dict]:
    rows=web_search(query, limit=max(3,min(limit,10))); created=[]; seen=set()
    for row in rows:
        url=str(row.get('url') or '')
        host=urlparse(url).netloc.lower().removeprefix('www.')
        if not host or host in seen: continue
        seen.add(host)
        title=re.sub(r'\s+',' ',str(row.get('title') or host)).strip()
        snippet=re.sub(r'\s+',' ',str(row.get('snippet') or '')).strip()
        score=_score(title,snippet)
        lead=add_lead(title[:160], website=url, source='opportunity_hunter', problem=snippet[:500], score=score)
        created.append(lead)
    return created


def hunt_and_register(query: str, limit: int = 8) -> str:
    leads=hunt(query, limit)
    if not leads: return 'Nenhum lead novo encontrado nessa busca.'
    avg=round(sum(int(x.get('score',0)) for x in leads)/len(leads))
    add_opportunity(f'Prospecção: {query}', source='opportunity_hunter', revenue_score=7, speed_score=7,
                    fit_score=max(1,min(10,round(avg/10))), cost_score=2, risk_score=3,
                    notes=f'{len(leads)} leads gerados automaticamente.')
    out=[f'Opportunity Hunter encontrou {len(leads)} leads:']
    for x in leads[:10]: out.append(f"- [{x['id']}] {x['name']} | score={x['score']} | {x.get('website','')}")
    return '\n'.join(out)
