# Hermes v4.5 — Unified Identity + Connected Assistant

## Objetivo

Permitir que canais externos autorizados, inicialmente Telegram, usem as integrações do mesmo usuário Freud sem copiar tokens OAuth para o Hermes.

```text
Telegram
   |
   | identidade do canal + token de infraestrutura
   v
Hermes Core
   |
   | Freud Channel Broker
   v
Freud Back
   |
   +--> resolve channel_links -> organizationId/userId
   +--> Calendar / Gmail / GitHub / WhatsApp
   +--> Approvals para ações externas
```

## Segurança

- Tokens OAuth e credenciais de integrações continuam somente no Freud/banco criptografado.
- `FREUD_CHANNEL_BROKER_TOKEN` é segredo de infraestrutura, não segredo de usuário.
- O vínculo exige código temporário gerado por uma sessão Freud autenticada.
- O código expira em 10 minutos e é invalidado após o uso.
- Uma identidade Telegram não pode ficar vinculada simultaneamente a dois usuários Freud.
- Escritas externas continuam usando o Approval Center do Freud.

## Configuração

No backend Freud:

```env
FREUD_CHANNEL_BROKER_TOKEN=<segredo-forte-compartilhado>
```

No Hermes, em `~/.config/hermes/core-api.env`:

```env
FREUD_CHANNEL_BROKER_URL=https://SEU_BACKEND_FREUD/api/channel-broker
FREUD_CHANNEL_BROKER_TOKEN=<mesmo-segredo-forte>
```

Use rede privada/Tailscale/WireGuard sempre que disponível. Se o broker passar pela internet pública, HTTPS é obrigatório.

## Vínculo

1. No Freud, abra Integrações e conecte Telegram.
2. O Freud gera uma mensagem temporária como `conectar freud A1B2C3D4E5`.
3. Envie essa mensagem ao bot Hermes autorizado.
4. O Hermes envia somente canal, Telegram user id, chat id e código ao broker.
5. Freud resolve o código e associa o Telegram ao `organizationId/userId` autenticado que criou o código.

## Depois do vínculo

Exemplos no Telegram:

```text
status conectado
quais integrações eu tenho conectadas?
veja minha agenda de hoje
veja meus e-mails importantes
quais repositórios tenho no GitHub?
o que precisa da minha atenção hoje?
```

O Connected Router consulta o catálogo de ferramentas do Freud, seleciona a ferramenta adequada e usa somente o resultado real retornado.

## Limite atual

A v4.5 unifica identidade e ferramentas conectadas. A memória local do Core ainda deve ser considerada por-runtime. Para produto multiusuário em um único Hermes compartilhado, o próximo passo é tenant-scope completo de memória/jobs/contexto ou runtimes dedicados por usuário/organização.
