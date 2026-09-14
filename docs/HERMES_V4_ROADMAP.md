# Hermes v4 — Autonomous Execution Runtime

Objetivo: transformar o Hermes em uma inteligência local-first capaz de receber missões, planejar, executar, validar, retomar após falhas e operar ferramentas reais com memória, segurança e aprovação.

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

## Fase 2 — Runtime autônomo avançado
- [ ] Loop até Definition of Done
- [ ] Cancelar/pausar/retomar jobs
- [ ] Prioridade e dependências entre jobs
- [ ] Execução paralela controlada
- [ ] Resource manager por CPU/RAM
- [ ] Deadline e orçamento por missão
- [ ] Checkpoints ricos com artefatos
- [ ] Retry adaptativo e backoff
- [ ] Dead-letter queue
- [ ] Auditoria completa de decisões e ações

## Fase 3 — Web & Research
- [ ] SearXNG self-hosted
- [ ] Playwright/browser worker
- [ ] Crawler de empresas
- [ ] Extração estruturada de contatos/dados
- [ ] Auditoria automática de sites
- [ ] Deep research multi-fonte
- [ ] Evidências e rastreabilidade das fontes
- [ ] Lead scoring automático

## Fase 4 — Business/Revenue OS
- [ ] Goal-to-Revenue Engine
- [ ] Pipeline comercial automático
- [ ] Enriquecimento de leads
- [ ] Follow-up scheduler
- [ ] Propostas comerciais
- [ ] A/B de abordagem
- [ ] Strategy Engine baseado em resultados
- [ ] Opportunity Radar contínuo
- [ ] Daily/Weekly CEO Review

## Fase 5 — Developer OS
- [ ] GitHub remoto via Freud como integração principal
- [ ] Repo/branch/commit/PR via ferramentas autorizadas
- [ ] Build/test/review automatizados
- [ ] Agente de programação contínua
- [ ] Landing Factory integrada
- [ ] Deploy Vercel/Dokploy
- [ ] Rollback automático
- [ ] GitHub watcher/CI repair

## Fase 6 — Multiagentes
- [ ] Researcher
- [ ] Developer
- [ ] Sales
- [ ] Marketing
- [ ] DevOps
- [ ] Finance
- [ ] Reviewer/Validator
- [ ] Orquestrador com delegação dinâmica

## Fase 7 — Memória e conhecimento
- [ ] Embeddings locais leves
- [ ] RAG por projeto
- [ ] Knowledge graph
- [ ] Compressão e gestão de contexto
- [ ] Aprendizado por resultado real
- [ ] Memória multiusuário via Freud

## Fase 8 — Observabilidade & Self-Healing
- [ ] Mission Control
- [ ] Timeline de atividades
- [ ] Métricas de jobs e ferramentas
- [ ] Health supervisor independente
- [ ] Self-healing seguro
- [ ] Auto-update com smoke test/rollback
- [ ] Self-debugger

## Fase 9 — Skills
- [ ] Manifesto padrão de skills
- [ ] Permissões por skill
- [ ] Skill registry persistente
- [ ] Skill Store privada
- [ ] Skill Generator com testes e aprovação

## Fase 10 — Voz e interfaces
- [ ] STT local
- [ ] TTS local
- [ ] Conversa por voz em tempo real
- [ ] Wake word opcional
- [ ] App Freud como interface principal
- [ ] Telegram/app/voz compartilhando contexto
- [ ] Approvals Center unificado

## Regras permanentes
1. Ações internas seguras podem ser autônomas.
2. Ações externas/sensíveis respeitam política de aprovação.
3. Credenciais do usuário ficam no Freud/banco criptografado, não no código nem no modelo.
4. Estado pessoal fica fora do Git.
5. Toda missão importante deve ser durável, auditável e retomável.
6. Nenhuma etapa pode ser marcada concluída sem validação.
7. O Hermes deve continuar sozinho até concluir ou encontrar um bloqueio real.
