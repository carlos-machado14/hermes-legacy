from __future__ import annotations

# Prefixo estático para maximizar reutilização do KV cache do llama.cpp.
# O modelo só classifica intenção; datas/recorrência detalhadas continuam sendo
# extraídas deterministicamente pelos parsers/executores locais.
SYSTEM = '''/no_think
Só JSON. Classifique PT-BR informal.
Campos: m,r,a,e,s,ref,p,c,resp.
m=chat|query|action|followup
r=time|task|automation|assistant|research|developer|devops|memory|chat
a=none|list|create|remove|update|pause|resume|run|complete|reschedule|answer|search
e=day|routine|reminder|alert|event|commitment|schedule|task|unknown
s=single|all|filtered|selection|unknown
p=today|tomorrow|this_week|next_week|this_month|next_month|unknown
c=0..1. Pergunta nunca vira ação. Não invente IDs. Se ação ambígua: r=chat,a=answer,resp=pergunta curta.
Exemplos:
U:o que tenho amanhã
J:{"m":"query","r":"time","a":"list","e":"day","s":"filtered","p":"tomorrow","c":0.99}
U:me lembra amanhã 9h de pagar a conta
J:{"m":"action","r":"time","a":"create","e":"reminder","s":"single","p":"tomorrow","ref":"pagar a conta","c":0.99}
U:cancela todos meus compromissos da agenda
J:{"m":"action","r":"time","a":"remove","e":"commitment","s":"all","p":"unknown","c":0.99}
U:terminei a tarefa do contrato
J:{"m":"action","r":"task","a":"complete","e":"task","s":"filtered","ref":"contrato","p":"unknown","c":0.99}'''
