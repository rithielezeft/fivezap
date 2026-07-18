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
- **[FIX 2026-02-P0]** `create_trial` P2P/Hybrid: após POST /api/trial_users, chama `POST /api/users/{id}/change_system` com `{system_id: 2}` (P2P) ou `{system_id: 3}` (Hybrid) — painel.fun sempre cria como IPTV por padrão
- **[FIX 2026-02-P0]** DreamTV validate+playlist é chamado APENAS para IPTV+MAC. Hybrid não passa por DreamTV — o `macaddr` já é enviado no `POST /api/trial_users` e o `change_system=3` completa o fluxo.
- **[FIX 2026-02-P0]** Bot MAC retry: cliente tem **3 tentativas** para enviar MAC no formato correto (AA:BB:CC:DD:EE:FF, aceita também `-` e sem separador). Cada tentativa inválida explica o formato e mostra tentativas restantes. Após 3 falhas o bot desiste graciosamente e limpa o estado.
- **[FIX 2026-02-P0]** Pay link vinculado ao painel trial id: `order_nsu=trial-{painel_id}-{months}m` e `redirect_url=/pay/{painel_id}` — webhook InfinitePay agora encontra o cliente correto do trial
- **[FIX 2026-02-P0]** `create_trial` agora envia `system` como inteiro no payload: 1=IPTV, 2=P2P, 3=Hybrid
- **[FIX 2026-02-P0]** `resync_user` usa endpoints exatos do painel.fun: `/api/users/{id}/resync_p2p` e `/api/users/{id}/resync_hybrid`

- Dashboard com métricas (testes hoje, ativos, vencendo, receita 7d, chart, distribuição)
- CRUD Clientes locais (mantido) + **NOVA página Clientes puxada direto do painel.fun** com renovação e criação de teste inline
- Trials — POST via api.controle.fit + 2Captcha Turnstile + curl_cffi (bypass Cloudflare TLS)
- **Templates de comandos com `trigger_source`**: cliente | admin | ambos (admin pode enviar comando ao cliente e o bot aciona o teste)
- WhatsApp: QR code, status, envio manual (**agora com suporte a IMAGEM**), incoming webhook processado pelo bot
- **whatsapp-web.js@1.34.7 com LID support**: preserva `@lid` end-to-end (privacidade nova do WhatsApp Web), captura `msg.notifyName` como nome real do cliente
- **Dedup de mensagens** em 2 camadas: (a) Node por msg.id TTL 60s; (b) Backend por phone+direction+body TTL 30s — evita criar trial duplicado
- Conversas (histórico e envio)
- **Pagamentos InfinitePay reescrito** conforme docs oficiais: sanitize handle, error surfacing, aceita `url`/`checkout_url`/`payment_url`, botão "Testar link R$ 1,00" em Configurações com payload+response completos
- **Auto-criar customer local** a partir do painel.fun quando `/pay/{id}` é chamado com id que só existe no painel — evita 404 no fluxo de renovação
- Webhook InfinitePay renova cliente no painel.fun automaticamente (chama `painel.renew_user(package_id)` conforme meses)
- **Links de pagamento InfinitePay no template do teste**: `{pay_link}` (padrão 1m) + `{pay_link_1m}`, `{pay_link_3m}`, `{pay_link_6m}`, `{pay_link_12m}` — gerados pelo bot direto quando trial é criado. Fallback para `/pay/{id}` se InfinitePay falhar.
- **Nome do cliente do WhatsApp** salvo automaticamente em `customers.name` (via `msg.notifyName` capturado no Node)
- **Extrator de WhatsApp**: `as_number` (normalizado) → `reseller_notes` (regex BR)
- **Extrator de sistema**: campo `system` int do painel (1=iptv, 2=p2p, 3=hybrid) → package_id → keywords → MAC
- **Paginação completa** do painel.fun (`page`, `per`, `reseller`, `order_by=exp_date,asc`, meta.pages)
- **Status/vencimento**: `exp_date` unix → dias, `enabled` 0/1 → active/expiring_soon/expired
- **Filtros na UI Clientes**: por sistema (IPTV/P2P/Hybrid) + por status (Vencidos/Vencendo/Ativos) + botão "Notificar vencendo"
- **Notificações editáveis** com corpo + imagem opcional (5 eventos: 3d, 1d, 0d, renewal_success, trial_ready), com prévia estilo WhatsApp e botão "Enviar teste"
- Scheduler: itera usuários do painel.fun a cada hora e envia cada mensagem personalizada com `{name}`, `{expires_at}`, `{pay_link}` (customer_id do painel), respeitando `notification_days`
- **Preços em R$** (35,00 formato brasileiro) — internamente convertidos para centavos
- **Endpoint de diagnóstico do bot** (`GET /api/templates/bot-diagnostics`) — mostra templates ativos + últimas 20 mensagens + últimos 20 eventos do bot
- **Deploy automation**: `update.sh` (git safe pull + rollback + health check), `reinstall.sh` (nuclear reset), `setup-auto-update.sh` (systemd timer daily), Docker Compose (backend + whatsapp + frontend), `DEPLOY.md` completo

## Backlog / P1
- Autenticação admin (senha) para o painel
- Painel: página de logs completa
- Botão renovar manualmente do admin (para clientes sem link)
- QR code refresh melhorado / reconnect
- Fluxo "responder SIM no WhatsApp gera link" (P2)
- Botão "Verificar pagamento" na tela Payments via `/payment_check`
- Dashboard saldo 2Captcha + créditos painel.fun
- Refactor: rotas em subpastas /app/backend/routes por domínio

## Known Notes
- InfinitePay handle deve ser configurado em Configurações antes de gerar cobranças
- painel.fun API endpoints (login, trial_users, renewal) foram implementados de acordo com o enunciado; se retornarem 4xx, os erros são logados
- Para Raspberry: rodar `whatsapp-service` como serviço systemd separado, apontando `BACKEND_WEBHOOK_URL` para o backend local
