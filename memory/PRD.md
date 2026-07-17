# WhatsFlow — PRD

## Original Problem Statement
Sistema para Raspberry Pi que conecta WhatsApp via whatsapp-web.js, envia/recebe mensagens de clientes, identifica templates de mensagens (comandos) e cria testes automaticamente no painel.fun.

**Painel**: api.controle.fit (login Rithiele2026 / Rithi0518)  
**Captcha**: 2Captcha `c3233ff53fddf3e816b0cf78c2ccef61` (Cloudflare Turnstile)  
**Trial package_id**: 61  
**Pacotes de renovação**:
- P2P + Hybrid: 1m=17, 3m=42, 6m=55, 12m=57
- IPTV (Dream TV): 1m=17, 3m=43, 6m=56, 12m=58

**Pagamentos**: InfinitePay Gateway (checkout.infinitepay.io) — handle configurável no admin.  
**URLs públicas**: `/teste` (formulário), `/pay/{customer_id}` (renovação).  
**Fuso**: America/Sao_Paulo. **DB**: SQLite local.

## Architecture
- **Backend**: FastAPI + SQLite (aiosqlite) na porta 8001, prefixo `/api`
- **WhatsApp Service**: Node.js + whatsapp-web.js na porta 3001 (localhost), spawn pelo backend
- **Frontend**: React 19 + Shadcn UI + Phosphor Icons + recharts (dark theme, Cabinet Grotesk + IBM Plex Sans)

## Implemented (2026-02)
- Dashboard com métricas (testes hoje, ativos, vencendo, receita 7d, chart, distribuição)
- CRUD Clientes (IPTV/P2P/Hybrid + MAC + credenciais painel)
- Trials — POST via api.controle.fit + 2Captcha Turnstile
- Templates de comandos (bot lê msg do WhatsApp e cria teste)
- WhatsApp: QR code, status, envio manual, incoming webhook processado pelo bot
- Conversas (histórico e envio)
- Pagamentos via InfinitePay checkout (`/links`) + webhook renova via API
- Configurações completas (todas as chaves)
- Público: `/teste` (form) e `/pay/{customer_id}` (planos)
- Scheduler: notificações de vencimento via WhatsApp (dias configuráveis 3,1,0)

## Backlog / P1
- Autenticação admin (senha) para o painel
- Painel: página de logs completa
- Botão renovar manualmente do admin (para clientes sem link)
- Testes automatizados backend
- QR code refresh melhorado / reconnect

## Known Notes
- InfinitePay handle deve ser configurado em Configurações antes de gerar cobranças
- painel.fun API endpoints (login, trial_users, renewal) foram implementados de acordo com o enunciado; se retornarem 4xx, os erros são logados
- Para Raspberry: rodar `whatsapp-service` como serviço systemd separado, apontando `BACKEND_WEBHOOK_URL` para o backend local
