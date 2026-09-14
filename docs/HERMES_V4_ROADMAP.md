# Hermes v4 — Autonomous Execution Runtime

Objetivo: transformar o Hermes em uma inteligência local-first geral, capaz de conversar, lembrar, receber missões, planejar, executar, validar, retomar após falhas e operar ferramentas reais com memória, segurança e aprovação. Leads/CRM são apenas uma capacidade entre muitas.

## Fase 1 — Fundação durável ✅
- [x] Job Store SQLite
- [x] Checkpoints por etapa
- [x] Recuperação de jobs interrompidos após restart
- [x] Planner estruturado
- [x] Executor sequencial com retry
- [x] Validator por etapa e final
- [x] Worker systemd dedicado
- [x] Comandos conversacionais de missões/jobs
- [x] Fastpath assíncrono sem timeout curto do Telegram

## Fase 2 — Universal Agent Runtime ✅ base v4.2
- [x] Roteamento multi-domínio
- [x] Catálogo de agentes especialistas internos
- [x] Registry universal de capacidades
- [x] Universal Planner com Definition of Done
- [x] Missões duráveis usando planner multi-domínio
- [x] Contexto/memória únicos entre os domínios
- [x] Política explícita para ações externas/sensíveis
- [ ] Pausar/cancelar/retomar jobs individualmente
- [ ] Prioridade e dependências entre jobs
- [ ] Execução paralela controlada
- [ ] Resource manager por CPU/RAM
- [ ] Deadline e orçamento por missão
- [ ] Dead-letter queue
- [ ] Auditoria completa de decisões e ações

## Fase 3 — Web & Research ✅ fundação v4.1
- [x] SearXNG self-hosted
- [x] Playwright/browser worker
- [x] Crawler web
- [x] Extração estruturada de contatos/dados
- [x] Auditoria automática de sites
- [x] Deep research multi-fonte base
- [x] Evidências e rastreabilidade base
- [x] Lead scoring como capacidade opcional
- [ ] Browser actions autenticadas via Freud
- [ ] Pesquisa iterativa até cobertura/Definition of Done

## Fase 4 — Personal Assistant OS
- [ ] Agenda/calendário integrado
- [ ] Inbox universal
- [ ] Lembretes/contexto temporal
- [ ] Planejamento diário adaptativo
- [ ] Preparação pré-reunião
- [ ] Follow-up pessoal pós-reunião
- [ ] Decisões e compromissos rastreados

## Fase 5 — Business/Revenue OS
- [ ] Goal-to-Revenue Engine
- [ ] Pipeline comercial automático
- [ ] Enriquecimento de leads
- [ ] Follow-up scheduler
- [ ] Propostas comerciais
- [ ] A/B de abordagem
- [ ] Strategy Engine baseado em resultados
- [ ] Opportunity Radar contínuo
- [ ] Daily/Weekly CEO Review

## Fase 6 — Developer OS
- [ ] GitHub remoto via Freud como integração principal
- [ ] Repo/branch/commit/PR via ferramentas autorizadas
- [ ] Build/test/review automatizados
- [ ] Agente de programação contínua
- [ ] Landing Factory integrada
- [ ] Deploy Vercel/Dokploy
- [ ] Rollback automático
- [ ] GitHub watcher/CI repair

## Fase 7 — Especialistas e orquestração
- [x] General Assistant
- [x] Researcher
- [x] Developer
- [x] DevOps
- [x] Business
- [x] Personal Assistant
- [x] Communication
- [x] Finance
- [x] Reviewer/Validator
- [ ] Delegação dinâmica com execução paralela
- [ ] Especialistas com ferramentas remotas via Freud

## Fase 8 — Memória e conhecimento
- [ ] Embeddings locais leves
- [ ] RAG por projeto
- [ ] Knowledge graph
- [ ] Compressão e gestão de contexto
- [ ] Aprendizado por resultado real
- [ ] Memória multiusuário via Freud

## Fase 9 — Observabilidade & Self-Healing
- [ ] Mission Control
- [ ] Timeline de atividades
- [ ] Métricas de jobs e ferramentas
- [ ] Health supervisor independente
- [ ] Self-healing seguro
- [ ] Auto-update com smoke test/rollback
- [ ] Self-debugger

## Fase 10 — Skills
- [ ] Manifesto padrão de skills
- [ ] Permissões por skill
- [ ] Skill registry persistente
- [ ] Skill Store privada
- [ ] Skill Generator com testes e aprovação

## Fase 11 — Voz e interfaces
- [ ] STT local
- [ ] TTS local
- [ ] Conversa por voz em tempo real
- [ ] Wake word opcional
- [ ] App Freud como interface principal
- [ ] Telegram/app/voz compartilhando contexto
- [ ] Approvals Center unificado

## Regras permanentes
1. Hermes é uma única inteligência geral; domínios e especialistas são capacidades internas.
2. Ações internas seguras podem ser autônomas.
3. Ações externas/sensíveis respeitam política de aprovação.
4. Credenciais do usuário ficam no Freud/banco criptografado, não no código nem no modelo.
5. Estado pessoal fica fora do Git.
6. Toda missão importante deve ser durável, auditável e retomável.
7. Nenhuma etapa pode ser marcada concluída sem validação.
8. O Hermes deve continuar sozinho até concluir ou encontrar um bloqueio real.
