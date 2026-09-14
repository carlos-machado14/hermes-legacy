#!/usr/bin/env python3
from __future__ import annotations

import json, os, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from event_bus import recent as recent_events
from incident_store import recent_incidents
from memory_store import recent as recent_memory
from project_registry import list_projects, upsert_project, remove_project
from project_ops import project_status, restart_project
from goal_manager import list_goals, create_goal
from task_manager import list_tasks, create_task, complete_task
from opportunity_engine import list_items as list_opportunities, add as add_opportunity
from personal_memory import profile as personal_profile
from skill_registry import list_skills
from context_builder import snapshot as context_snapshot
from decision_log import recent as recent_decisions
from proactive_engine import daily_brief, weekly_review
from proactive_settings import load as proactive_settings, enable as enable_proactive, disable as disable_proactive
from autonomy_settings import load as autonomy_settings, enable as enable_autonomy, disable as disable_autonomy
from action_queue import list_actions, reject as reject_action
from goal_execution_engine import run_cycle, approve_and_execute, capability_summary
from lead_manager import list_leads, add_lead, update_lead
from crm_engine import summary as crm_summary, hot_leads, followups_due
from opportunity_hunter import hunt
from deep_research import research as deep_research
from learning_engine import ranked_signals, record_outcome

ROOT = Path.home() / '.hermes/core-v2'
HOST = os.getenv('HERMES_CORE_API_HOST', '127.0.0.1')
PORT = int(os.getenv('HERMES_CORE_API_PORT', '8090'))
TOKEN = os.getenv('HERMES_CORE_API_TOKEN', '').strip()


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    raw=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    handler.send_response(status); handler.send_header('Content-Type','application/json; charset=utf-8'); handler.send_header('Content-Length',str(len(raw))); handler.end_headers(); handler.wfile.write(raw)


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not TOKEN: return True
    return handler.headers.get('Authorization','') == f'Bearer {TOKEN}'


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length=int(handler.headers.get('Content-Length','0') or 0)
    if length <= 0: return {}
    return json.loads(handler.rfile.read(min(length,1024*1024)).decode('utf-8'))


def _run_core(message: str) -> tuple[int,str]:
    p=subprocess.run([str(ROOT/'venv/bin/python'),str(ROOT/'core_entry.py'),message],text=True,capture_output=True,timeout=900,cwd=str(ROOT))
    return p.returncode,(p.stdout or p.stderr or '').strip()


def _web_health() -> dict:
    try:
        from web_search_engine import health
        return health()
    except Exception as exc:
        return {'ok':False,'error':str(exc)}


class Handler(BaseHTTPRequestHandler):
    server_version='HermesCoreAPI/4.1'
    def log_message(self,fmt: str,*args) -> None: return
    def _guard(self) -> bool:
        if not _auth_ok(self): _json(self,401,{'ok':False,'error':'unauthorized'}); return False
        return True

    def do_GET(self) -> None:
        if not self._guard(): return
        path=urlparse(self.path).path
        if path=='/health': _json(self,200,{'ok':True,'version':'4.1','api':'active','mode':'durable-autonomous-web-runtime'})
        elif path=='/web/status': _json(self,200,_web_health())
        elif path=='/events': _json(self,200,{'ok':True,'events':recent_events(100)})
        elif path=='/memory': _json(self,200,{'ok':True,'memory':recent_memory(100)})
        elif path=='/incidents': _json(self,200,{'ok':True,'incidents':recent_incidents(100)})
        elif path=='/projects': _json(self,200,{'ok':True,'projects':list_projects()})
        elif path=='/goals': _json(self,200,{'ok':True,'goals':list_goals()})
        elif path=='/tasks': _json(self,200,{'ok':True,'tasks':list_tasks()})
        elif path=='/opportunities': _json(self,200,{'ok':True,'opportunities':list_opportunities(None)})
        elif path=='/profile': _json(self,200,{'ok':True,'profile':personal_profile()})
        elif path=='/skills': _json(self,200,{'ok':True,'skills':list_skills()})
        elif path=='/context': _json(self,200,{'ok':True,'context':context_snapshot()})
        elif path=='/decisions': _json(self,200,{'ok':True,'decisions':recent_decisions(100)})
        elif path=='/brief/today': _json(self,200,{'ok':True,'brief':daily_brief()})
        elif path=='/brief/week': _json(self,200,{'ok':True,'brief':weekly_review()})
        elif path=='/proactive': _json(self,200,{'ok':True,'settings':proactive_settings()})
        elif path=='/autonomy': _json(self,200,{'ok':True,'settings':autonomy_settings(),'capabilities':capability_summary()})
        elif path=='/actions': _json(self,200,{'ok':True,'actions':list_actions(None,100)})
        elif path=='/leads': _json(self,200,{'ok':True,'leads':list_leads(None)})
        elif path=='/crm': _json(self,200,{'ok':True,'summary':crm_summary(),'hot_leads':hot_leads(10),'followups_due':followups_due(20)})
        elif path=='/learning': _json(self,200,{'ok':True,'signals':ranked_signals(50)})
        else: _json(self,404,{'ok':False,'error':'not_found'})

    def do_POST(self) -> None:
        if not self._guard(): return
        path=urlparse(self.path).path
        try: body=_read_body(self)
        except Exception as exc: _json(self,400,{'ok':False,'error':f'invalid_json: {exc}'}); return

        if path=='/message':
            message=str(body.get('message') or '').strip()
            if not message: _json(self,400,{'ok':False,'error':'message_required'}); return
            try:
                code,reply=_run_core(message); _json(self,200 if code==0 else 500,{'ok':code==0,'reply':reply})
            except subprocess.TimeoutExpired: _json(self,202,{'ok':True,'status':'still_running','message':'core_processing'})
        elif path=='/web/search':
            query=str(body.get('query') or '').strip()
            if not query: _json(self,400,{'ok':False,'error':'query_required'})
            else:
                try:
                    from web_search_engine import search
                    _json(self,200,{'ok':True,'results':search(query,int(body.get('limit',8)))})
                except Exception as exc: _json(self,503,{'ok':False,'error':str(exc)})
        elif path=='/web/audit':
            url=str(body.get('url') or '').strip()
            if not url: _json(self,400,{'ok':False,'error':'url_required'})
            else:
                try:
                    from site_auditor import audit
                    _json(self,200,audit(url))
                except Exception as exc: _json(self,503,{'ok':False,'error':str(exc)})
        elif path=='/web/crawl':
            url=str(body.get('url') or '').strip()
            if not url: _json(self,400,{'ok':False,'error':'url_required'})
            else:
                try:
                    from site_crawler import crawl
                    _json(self,200,crawl(url,int(body.get('max_pages',5))))
                except Exception as exc: _json(self,503,{'ok':False,'error':str(exc)})
        elif path=='/proactive/enable': _json(self,200,{'ok':True,'settings':enable_proactive()})
        elif path=='/proactive/disable': _json(self,200,{'ok':True,'settings':disable_proactive()})
        elif path=='/autonomy/enable': _json(self,200,{'ok':True,'settings':enable_autonomy()})
        elif path=='/autonomy/disable': _json(self,200,{'ok':True,'settings':disable_autonomy()})
        elif path=='/autonomy/run': _json(self,200,{'ok':True,'report':run_cycle()})
        elif path=='/actions/approve':
            ref=str(body.get('ref') or '').strip()
            try: _json(self,200,{'ok':True,'action':approve_and_execute(ref)})
            except KeyError: _json(self,404,{'ok':False,'error':'action_not_found'})
        elif path=='/actions/reject':
            ref=str(body.get('ref') or '').strip()
            try: _json(self,200,{'ok':True,'action':reject_action(ref)})
            except KeyError: _json(self,404,{'ok':False,'error':'action_not_found'})
        elif path=='/projects':
            try: _json(self,200,{'ok':True,'project':upsert_project(dict(body))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        elif path=='/projects/remove':
            name=str(body.get('name') or '').strip(); _json(self,200,{'ok':True,'removed':remove_project(name) if name else False})
        elif path=='/projects/status':
            name=str(body.get('name') or '').strip(); report=project_status(name) if name else {'ok':False,'error':'name_required'}; _json(self,200 if report.get('ok') else 400,report)
        elif path=='/projects/restart':
            name=str(body.get('name') or '').strip(); report=restart_project(name) if name else {'ok':False,'error':'name_required'}; _json(self,200 if report.get('ok') else 409,report)
        elif path=='/goals':
            try: _json(self,200,{'ok':True,'goal':create_goal(str(body.get('title') or ''),target_value=body.get('target_value'),target_unit=body.get('target_unit'),deadline=body.get('deadline'),category=str(body.get('category') or 'general'),notes=str(body.get('notes') or ''))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        elif path=='/tasks':
            try: _json(self,200,{'ok':True,'task':create_task(str(body.get('title') or ''),goal_id=body.get('goal_id'),priority=str(body.get('priority') or 'medium'),due=body.get('due'))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        elif path=='/tasks/complete':
            try: _json(self,200,{'ok':True,'task':complete_task(str(body.get('ref') or ''))})
            except Exception as exc: _json(self,404,{'ok':False,'error':str(exc)})
        elif path=='/opportunities':
            try: _json(self,200,{'ok':True,'opportunity':add_opportunity(str(body.get('title') or ''),source=str(body.get('source') or 'api'),revenue_score=int(body.get('revenue_score',5)),speed_score=int(body.get('speed_score',5)),fit_score=int(body.get('fit_score',5)),cost_score=int(body.get('cost_score',5)),risk_score=int(body.get('risk_score',5)),notes=str(body.get('notes') or ''))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        elif path=='/leads':
            try: _json(self,200,{'ok':True,'lead':add_lead(str(body.get('name') or ''),website=str(body.get('website') or ''),niche=str(body.get('niche') or ''),contact=str(body.get('contact') or ''),problem=str(body.get('problem') or ''),offer=str(body.get('offer') or ''),estimated_value=body.get('estimated_value'),source=str(body.get('source') or 'api'),score=int(body.get('score',50)),notes=str(body.get('notes') or ''))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        elif path=='/leads/update':
            ref=str(body.pop('ref','') or '').strip()
            try: _json(self,200,{'ok':True,'lead':update_lead(ref,**body)})
            except KeyError: _json(self,404,{'ok':False,'error':'lead_not_found'})
        elif path=='/hunter/run':
            query=str(body.get('query') or '').strip()
            if not query: _json(self,400,{'ok':False,'error':'query_required'})
            else: _json(self,200,{'ok':True,'leads':hunt(query,int(body.get('limit',8)))})
        elif path=='/research/deep':
            query=str(body.get('query') or '').strip()
            if not query: _json(self,400,{'ok':False,'error':'query_required'})
            else: _json(self,200,{'ok':True,'report':deep_research(query,int(body.get('limit',6)))})
        elif path=='/learning/outcome':
            try: _json(self,200,{'ok':True,'event':record_outcome(str(body.get('category') or 'business'),str(body.get('label') or ''),bool(body.get('success')),value=body.get('value'),notes=str(body.get('notes') or ''))})
            except Exception as exc: _json(self,400,{'ok':False,'error':str(exc)})
        else: _json(self,404,{'ok':False,'error':'not_found'})


def main() -> int:
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'Hermes Core API 4.1 listening on http://{HOST}:{PORT}',flush=True); server.serve_forever(); return 0


if __name__=='__main__': raise SystemExit(main())
