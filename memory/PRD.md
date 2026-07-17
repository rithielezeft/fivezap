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
- CRUD Clientes locais (mantido) + **NOVA página Clientes puxada direto do painel.fun** com renovação e criação de teste inline
- Trials — POST via api.controle.fit + 2Captcha Turnstile
- **Templates de comandos com `trigger_source`**: cliente | admin | ambos (admin pode enviar comando ao cliente e o bot aciona o teste)
- WhatsApp: QR code, status, envio manual (**agora com suporte a IMAGEM**), incoming webhook processado pelo bot
- Conversas (histórico e envio)
- Pagamentos via InfinitePay checkout (`/links`) + webhook renova via API
- **Notificações editáveis** com corpo + imagem opcional (5 eventos: 3d, 1d, 0d, renewal_success, trial_ready), com prévia estilo WhatsApp e botão "Enviar teste"
- Scheduler: itera usuários do painel.fun a cada hora e envia cada mensagem personalizada com `{name}`, `{expires_at}`, `{pay_link}` (customer_id do painel), respeitando `notification_days`
- **Preços em R$** (35,00 formato brasileiro) — internamente convertidos para centavos
- Configurações completas
- Público: `/teste` (form) e `/pay/{customer_id}` (planos)

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
