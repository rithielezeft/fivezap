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

- **[FIX + FEATURE 2026-02-22]** 3 melhorias verificadas pelo testing agent (100% success):
  1. **`reseller_notes` no painel só com o número** — antes gravava `"João — WhatsApp: +5511999998888"`, agora só `"+5511999998888"`. Nome continua no campo `name` normal.
  2. **Dropdown de timezone legível** — `<select>` com bg dark (#1a1a1a), colorScheme dark forçado, options com fundo dark. Opções: São Paulo, Fortaleza, Manaus, Rio Branco, NY, LA, Mexico City, Buenos Aires, Santiago, Bogotá, Lisboa, Madrid, Londres, Paris, Berlim, UTC (16 total).
  3. **Column selector + mobile responsive** nas páginas Clientes e Pagamentos — novo componente `components/ColumnPicker.jsx` com `useColumnVisibility` hook. Persist em localStorage (`customers-cols`, `payments-cols`). Presets "Padrão desktop" e "Padrão mobile (mínimo)". Em mobile (<768px) usa defaults reduzidos automaticamente. Tabelas ganharam `overflow-x-auto` + `min-w-[640px]` para scroll horizontal em mobile sem quebrar layout.

  Testes validados pelo testing agent: 8 data-testids em Customers, 9 em Payments, localStorage persiste após reload, timezone PUT/GET funciona (America/Sao_Paulo → Europe/Madrid → UTC).



- **[BATCH 2026-02-22]** 6 melhorias solicitadas:
  1. **Imagem opcional nos comandos** — nova coluna `image_url` em `command_templates` (com migration ALTER TABLE). UI de upload em Templates.jsx (usa endpoint `/api/uploads` existente). Bot envia imagem+caption quando o comando tem `image_url`.
  2. **Nome do cliente extraído da mensagem** — helper `_extract_name_from_message()` em `services/bot.py` parseia padrões "meu nome é X", "sou o X", "me chamo X", etc. Se encontrar → atualiza `customers.name`.
  3. **Perguntar nome antes do teste quando não temos** — se cliente não passa nome E o customer.name é placeholder (JID/telefone), bot pergunta "me diz seu primeiro nome" e aguarda resposta (state `_pending_name` com TTL 15min).
  4. **WhatsApp salvo em `reseller_notes` do painel** — `services/painel.create_trial` agora inclui `reseller_notes: "Nome — WhatsApp: +XXX"` no payload. Facilita achar o cliente no painel.
  5. **Auto-retry password format invalid** — `services/painel.create_trial` re-tenta até 3× com senha nova quando painel rejeita com "O campo password format is invalid".
  6. **Fuso horário selecionável** — nova setting `display_timezone` (default `America/Sao_Paulo`). Dropdown em Settings com principais TZ (São Paulo, NY, LA, London, Lisbon, Madrid, UTC, etc.). `formatDateBR()` no frontend agora lê essa setting via `getDisplayTimezone()`. App.jsx carrega no mount.

  Testes: `test_2026_02_22_batch2.py` (11 novos testes), `test_trial_error_messages.py` atualizado.

  **Pendente**: mobile responsivo + column selector nas páginas Clientes e Pagamentos.



- **[FIX 2026-02-22]** **Suporte internacional a números de WhatsApp**. Antes o sistema forçava `+55` em qualquer número — quebrava clientes do Espanha (+34), EUA (+1), Portugal (+351), UK (+44), Argentina (+54), etc. Agora `services/phone_extractor._clean()` respeita o `+` sign quando presente (E.164 padrão) e só prepende `55` em números bare de 10-11 dígitos (BR local). Números bare de 12-15 dígitos são preservados como-está (assume que já tem country code). Testes: `test_international_phones.py` (12 novos testes cobrindo ES/PT/US/UK/AR + BR).



- **[FEATURE 2026-02-22]** 4 melhorias solicitadas pelo usuário:
  1. **Admin alert com login do painel** — mensagem `💰 *Pagamento confirmado*` agora inclui linha `👥 Login: <painel_username>` para facilitar identificar o cliente no painel.
  2. **Dedup do scheduler robusto** — `set_setting(daily_key, "1")` agora acontece ANTES de `send_notification`, garantindo no máximo 1 tentativa por (user, threshold, dia). Também checagem extra via `notification_deliveries` (busca de entregas hoje) para bloquear duplicatas mesmo se o daily_key for perdido. Resolve o "duplicando templates de notificação de vencimento" reportado pelo usuário.
  3. **Botão "Reiniciar serviço" WhatsApp** — endpoint `POST /api/whatsapp/restart` derruba o processo Node e respawna (kill → sleep 2s → spawn → sleep 5s). Botão na página WhatsApp com confirmação. Resolve erros como "All connection attempts failed" e session zombies do Puppeteer.
  4. **Payment poller estendido para 7 dias** — `MAX_AGE_HOURS` de 48h → 168h em `services/payment_poller.py` + `routers/payments.py` (endpoint pay-page-return). Late payers (pix no 3º/5º dia) agora reconciliam. Resolve "pagamento pendente depois de 24h some".

  Testes: `test_2026_02_22_fixes.py` (6 novos testes).



- **[FEATURE 2026-02-22]** **Controle de intervalo de refresh do painel (economiza créditos 2Captcha)**. Nova setting `painel_refresh_interval_seconds` (default 300) em Configurações → Painel.fun. Aumentar (ex: 600, 1800) reduz frequência com que a página Clientes puxa do painel.fun. Impacto: (1) background loop em `server.py` — lê a config a cada tick, mudança tem efeito imediato; (2) endpoint `/api/painel/users` — só dispara refresh em background quando cache > TTL configurado; (3) removido `force: true` no mount de `Customers.jsx` — botão "Atualizar do painel" ainda existe para refresh manual. Mínimo protegido em 30s. Testes: `test_painel_refresh_ttl.py` (5 novos testes).



- **[FIX 2026-02-22]** **Mensagem amigável ao cliente quando cria teste falha**. Antes o cliente via `"Motivo: Create trial failed: 400 — {"message":"O campo password format is invalid."}"`. Agora vê `"⚠️ Poxa, tivemos um probleminha rápido gerando seu acesso. 🤖\n\nPor gentileza, 👉 envie *!teste iptv* novamente."`. Mapping específico para: password format invalid, username taken, insufficient credits, MAC invalid, rate limit (429), timeout. Detalhes técnicos vão para o admin via `send_admin_alert`. Testes: `test_trial_error_messages.py` (6 novos testes).



- **[FEATURE 2026-02-22]** **Anti-duplicata configurável em Configurações**. Duas novas settings:
  - `dedup_enabled` (true/false, default true) — liga/desliga globalmente o anti-duplicata da fila.
  - `dedup_window_minutes` (default 60) — janela em minutos para considerar uma mensagem "duplicada".
  Aplicado a todos os templates enviados via `send_notification` (delivery_queue). `send_hardcoded` (alertas do admin) ignora — sempre entrega. UI atualizada em Settings.jsx (grupo Notificações). Endpoint `/api/painel/notify-expired` lê a config para decidir se pede confirmação. Testes: `test_dedup_settings.py` (4 novos testes).



- **[FIX 2026-02-22 P0]** **Mensagens duplicadas em envios via fila (ex: notificar vencidos)**. Nova função `find_recent_delivery(phone, event_key, window_minutes)` em `services/delivery_queue.py` e parâmetros `dedup_window_minutes=60` + `force=False` em `enqueue()`. Se já existe entrega recente (`status=sent` dentro da janela, ou `status=pending` na fila), a chamada é no-op e retorna o id existente. `send_notification` propaga esses parâmetros; `send_hardcoded` desativa dedup (`dedup_window_minutes=0`) para não bloquear alertas do admin. Endpoint `/api/painel/notify-expired` agora tem fluxo de dois passos: 1ª chamada sem `force` → se detecta duplicados nos últimos 60min, retorna `{needs_confirmation, duplicates, duplicate_count, fresh_count, message}` sem enviar. 2ª chamada com `force=True` → bypassa dedup. Frontend `Customers.jsx` mostra segundo Dialog com lista dos duplicados (username, WhatsApp, "há N min", status entregue/na fila) e três botões: **Cancelar**, **Enviar só os N novos**, **Enviar mesmo assim**. Testado ao vivo: 2ª chamada retornou 7 duplicados corretamente. Testes: `test_delivery_dedup.py` (10 novos testes).



- **[FIX 2026-02-22 P0]** **Trial user que pagou continuava recebendo lembretes de "seu teste vai expirar"**. Causa: os `scheduled_reminders` (event_keys `trial_1h_reminder` +1h, `trial_expired` +3h) eram criados no INSERT do trial e nunca cancelados após pagamento. Fix: nova função `cancel_pending_for_phone(phone, event_keys)` em `services/reminders.py` marca as reminders pendentes com `sent=3` (cancelled). Chamada em `_process_payment_confirmation` no fluxo de sucesso quando temos `phone`. Testes: `test_cancel_trial_reminders.py` (3 testes, todos passam).

- **[FIX 2026-02-22 P0]** **Saldo do painel.fun mostrava null no dashboard**. Causa: iterávamos por endpoints antigos que retornavam 404 ou 200 sem campo de saldo (dashboard). Fix: descoberto via análise do bundle JS do painel.fun que o endpoint real é `GET /api/profile` (baseURL `https://api.controle.fit/api`). Adicionado como PRIMEIRO endpoint da lista em `services/painel.get_account_info`. Enriquecido `get_reseller_balance()` para retornar também `bonus_credits`, `last_recharge_credits`, `last_recharge_at`, `username`. Frontend `Dashboard.jsx` mostra o saldo formatado em pt-BR + bônus (se >0) + info da última recarga. Confirmado: painel real retorna `R$ 25,63`.



- **[FIX 2026-02-22 P0]** **Bug fantasma no cache de clientes (263 usuários mostrados vs. real do painel)**. Causa: `refresh_cache_task` em `routers/painel_users.py` usava estratégia MERGE — usuários deletados no painel permaneciam no cache SQLite para sempre. Fix: estratégia REPLACE. Quando painel retorna lista não-vazia, `_write_cache(painel_users + pending_trials)`. Trials injetados via `upsert_users_in_cache` são marcados com `_pending_from_trial=True` para sobreviver a UM refresh (até o painel refletir). Uma vez que o painel retorna o trial no seu próprio list, a flag é dropada. Testes: `/app/backend/tests/test_ghost_users_purge.py` (3 novos testes, todos passam).

- **[FIX 2026-02-22 P0]** **Trial que paga não recebe confirmação**. Causa: pay-links do trial são criados pelo `services/bot.py` (linha 448) com `order_nsu='trial-<painel_id>-<n>m'` diretamente no InfinitePay, SEM inserir uma linha em `payments` local. Quando o cliente pagava, `_process_payment_confirmation` retornava `payment not found` e o cliente ficava no vazio. Fix: quando `order_nsu` começa com `trial-` e não existe linha em `payments`, auto-cria uma linha `pending` no ato — extraindo `painel_id`, `plan_months`, `system_type` (via lookup em `trials`) e `paid_amount` do webhook — depois segue o fluxo normal (renew_user + template `renewal_success` para o cliente + `admin_alert`). Testes: `/app/backend/tests/test_trial_webhook_autocreate.py` (2 novos testes).

- **[FEATURE 2026-02-22 P1]** **Botão manual "Notificar Vencidos"** na página Clientes. Novo template `manual_expired_alert` em `services/default_templates.py`. Endpoints `GET /api/painel/expired` (preview) e `POST /api/painel/notify-expired` (aceita `user_ids: list[str]` — vazio = todos os vencidos com WhatsApp). Server re-valida `_status='expired'` para cada ID recebido (bloqueia envio a usuários ativos mesmo se o cliente passar IDs stale). Dialog no frontend (`Customers.jsx`) mostra tabela com checkboxes, pré-selecionando somente vencidos com WhatsApp, botões "Selecionar todos c/ WA" e "Limpar", com contagem em tempo real. Enfileiramento via `delivery_queue` (auto-retry 10s). Testes: `/app/backend/tests/test_notify_expired.py` (4 novos testes).


- **[FIX 2026-02-P0]** Bug: templates de produção com `system_type='iptv'` mas trigger/nome dizendo "Hybrid" ou "Dream TV" — Hybrid criava DreamTV e vice-versa. Solução: nova função defensiva `_infer_system_type(trigger, name, current)` no `bot.py` deriva o system_type correto do nome+trigger (prioridade: hybrid > p2p > iptv). `_run_trial_creation` usa o valor inferido em TODAS as chamadas downstream (painel.create_trial, INSERT trials, UPDATE customers, response template, InfinitePay, Mongo Atlas). Warning loggado pra admin corrigir o template.

- **[FIX 2026-02-P0 CRITICAL]** Cliente pagava InfinitePay mas confirmação nunca chegava. Causa: nenhum webhook real do InfinitePay chegava + `/payment_check` retornava `success:false` mesmo depois de pago. Solução: **token HMAC assinado por pagamento** (`secrets.token_urlsafe(24)`, 192 bits) embutido em `redirect_url` como `?t=<token>`. Cliente volta com token → frontend envia → backend valida via `secrets.compare_digest` → renova. `POST /api/payments/check-status/{id}` continua público mas só aceita com token correto.
- **[FIX 2026-02-P0]** `payment_check` estrito: só aceita quando InfinitePay retorna EXPLICITAMENTE `paid:true` (bug: `success:true` sozinho era interpretado como pago).
- **[FEATURE 2026-02]** Webhook agora loga headers completos (user-agent, referer, origin, x-forwarded-for) e aceita mais variações de campo/status (`event: payment.approved`, `status: captured`, etc).

- **[FIX 2026-02-P0 CRITICAL]** Payment poller estava sendo silenciosamente ignorado pelo FastAPI porque `@app.on_event('startup')` não funciona quando o app usa `lifespan=`. Testing agent (iteration_14) moveu `start_poller`/`stop_poller` para dentro do `lifespan()` async context. Sem esse fix, o polling ativo NUNCA rodava em produção — pagamentos ficariam `pending` para sempre se o webhook falhasse.
- **[FEATURE 2026-02]** Novo endpoint `GET /api/health/poller` público — expõe `{running, task_name, task_done}` do payment poller. Monitoring pode alertar se cair para `running:false`.
- **[FEATURE 2026-02]** 8 smoke/regression tests (`test_health_poller_smoke.py`) com AST guard que falha se alguém reintroduzir `@app.on_event`, e log scraper que falha se "Payment poller started" não aparecer no log após restart. Impede recorrência silenciosa.
- **[FEATURE 2026-02]** `services/payment_poller.py`: background asyncio task que a cada 20s chama `infinitepay.check_payment(order_nsu)` para cada pagamento `pending` (últimas 48h) e dispara renewal se `paid=true`. Idempotente com webhook.
- **[FEATURE 2026-02]** `POST /api/payments/check-status/{customer_id}` público — chamado pela página `/pay/{id}?ok=1` quando cliente volta do InfinitePay. Bypass do webhook para confirmação instantânea (~3s).
- **[FEATURE 2026-02]** `POST /api/payments/poll-now` admin — trigger manual de sweep para debug.
- **[FEATURE 2026-02]** Frontend `PublicPay.jsx`: quando URL tem `?ok=1`, mostra banner com estado (Confirmando… → Renovado ✅ ou Ainda processando ⏳) e faz polling automático até 10x (30s).

- **[FEATURE 2026-02]** InfinitePay pré-preenche apenas `customer.name = painel_username` (ex. "oscarnew") — amarra o pagamento ao usuário exato do painel. `customer.phone_number` fica em branco (opcional para o cliente preencher no checkout). Fallback para `full_name` caso o painel_username esteja vazio.

- **[FEATURE 2026-02]** InfinitePay checkout pré-preenchido: `POST /api/payments` agora passa `customer_name` (do Mongo/local) e `customer_phone` (whatsapp digits-only, sem `@c.us`/`@lid`) para o InfinitePay. Cliente não precisa digitar nome/telefone no checkout, InfinitePay associa pagamento ao painel_id.
- **[FIX 2026-02-P0]** Soft-failure detection avançado em `renew_user`: painel.fun envia respostas Rails-style com erro aninhado em `{"original": {"message": "..."}}`. Agora inspecionamos tanto top-level quanto `original` — evita marcar payment como renewed falsamente e mandar "Renovação confirmada" quando painel na verdade rejeitou.

- **[FIX 2026-02-P0]** `renew_user` soft-failure detection: painel.fun às vezes retorna HTTP 200 com `{"message": "You do not have access..."}` em vez de 4xx. Agora detectamos isso e lançamos `RuntimeError` para o webhook não marcar payment como `renewed` falsamente e não enviar "Renovação confirmada" errada. (bug crítico identificado pelo testing agent iteration_12)
- **[FIX 2026-02-P0]** WhatsApp service (`whatsapp-service/index.js`): `clearChromeStaleLocks()` remove SingletonLock/SingletonCookie/SingletonSocket/lockfile do userDataDir do Chrome no startup, resolvendo o erro "The browser is already running for /root/.whatsflow/wwebjs_auth/session-whatsflow". Também mata processos Chrome órfãos que estivessem segurando o profile. Graceful shutdown via SIGTERM/SIGINT.

- **[FIX 2026-02-P0]** Renovação via InfinitePay corrigida: endpoint agora é `POST /api/users/{painel_id}/renew` com body `{package_id: X}` (antes chamava `/api/renewal` errado).
- **[FEATURE 2026-02]** `order_nsu` no formato `renew-{painel_id}-{months}m` — webhook extrai o painel_id direto do NSU, não depende mais só de lookup local.
- **[FEATURE 2026-02]** Novo endpoint `POST /api/payments/reprocess/{payment_id}` — admin pode forçar renovação manualmente quando o webhook do InfinitePay não chegar. Idempotente.
- **[FIX 2026-02]** Webhook aceita múltiplas variações de payload (paid, status=approved/paid/completed, payment_status, etc) e formatos de campo (order_nsu, orderNsu, reference, external_reference, nsu).
- **[FEATURE 2026-02]** `POST /api/payments` (criar checkout do /pay) agora busca cliente também no Mongo Atlas antes de cair no cache do painel — clientes globais sempre encontrados.

- **[FIX 2026-02-P0 CRITICAL]** **Bug real do "Link inválido"**: o middleware auth bloqueava `/api/payments/customer/{id}` porque estava listado como `/api/pay/customer/` (path errado). Adicionado prefixo correto + `POST /api/payments` público (só para checkout) enquanto `GET /api/payments` continua admin-only.
- **[FEATURE 2026-02]** **MongoDB Atlas** como fonte da verdade global. `/api/payments/customer/{painel_id}` busca no Mongo PRIMEIRO — funciona em qualquer navegador, qualquer lugar do mundo, sem cookies, sem cache local. Todo trial criado (bot, form, admin) é upserted no Mongo automaticamente. Refresh da página de clientes espelha **TODOS** os usuários do painel para o Mongo — clientes legados (não só novos) têm seus links funcionando.
- Novo módulo `services/mongo_store.py`: `find_customer_by_painel_id`, `upsert_customer`, `ping`.
- `refresh_cache_task` agora sincroniza cada usuário do painel para o Mongo automaticamente.
- **[FIX 2026-02-P0]** `create_trial` P2P/Hybrid: após POST /api/trial_users, chama `POST /api/users/{id}/change_system` com `{system_id: 2}` (P2P) ou `{system_id: 3}` (Hybrid) — painel.fun sempre cria como IPTV por padrão
- **[FIX 2026-02-P0]** `/api/payments/customer/{id}` agora busca **primeiro na tabela local `trials`** por `trial_user_id` (o painel id que usamos em todos os `{pay_link}`). Depois cai para `customers.id`, `customers.painel_username`, e por último no cache do painel. Resultado: página `/pay/{id}` funciona **em qualquer navegador do mundo, mesmo com cache do painel vazio** — o SQLite da Raspberry Pi é a fonte da verdade.
- **[FEATURE 2026-02]** `upsert_users_in_cache` — cache do painel usa MERGE em vez de replace. Erros transientes do painel.fun (403, timeout, empty response) nunca apagam usuários já conhecidos, então links de pagamento de outros clientes continuam funcionando.
- **[FIX 2026-02-P0]** Payload de criação de trial atualizado para o formato real do painel.fun: envia `type` (1/2/3), `isHybrid: true/false`, `max_connections: 1`. Para Hybrid: `username: ""`, `password: ""` (painel gera server-side) + `macaddr` no payload inicial.
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

## Changelog Recente
- **2026-02**: Mensagem de MAC diferenciada por dispositivo — DreamTV (IPTV) instrui o cliente a olhar no *canto da tela do app DreamTV*; Hybrid/MAG/Formuler mantém "Menu → Configurações → Info do sistema". Helpers `_mac_where_to_find()` e `_mac_format_help()` em `services/bot.py`, com 6 novos testes em `tests/test_mac_instructions.py`.
- **2026-02**: **Notificação admin ao receber pagamento**. Novo setting `admin_whatsapp` (opcional) + helper `notifier.send_admin_alert()`. `_process_payment_confirmation` agora envia mensagem WhatsApp ao dono do painel em 3 cenários: (a) renovação bem-sucedida, (b) pagamento recebido mas `painel_id` não numérico/ausente (renovação manual necessária), (c) falha da renovação no painel.fun. Também corrigido bug em que `painel_id` extraído não-numérico era enviado ao `painel.renew_user` garantindo falha. Campo adicionado em `Settings.jsx`. 7 novos testes em `tests/test_admin_payment_alerts.py`.
- **2026-02**: **🔥 Correção crítica do webhook InfinitePay** — a doc oficial (`infinitepay.io/checkout`) confirma que o payload real do webhook **NÃO tem** `paid`/`status`/`event`; tem `transaction_nsu`, `paid_amount`, `invoice_slug`, `capture_method`, `order_nsu`, `receipt_url`. A lógica antiga não reconhecia esse payload → `paid=False` → confirmação nunca disparava. Agora detectamos pagamento por `transaction_nsu` + (`paid_amount>0` ou `capture_method` ou `invoice_slug`), mantendo fallbacks legados. Também adicionado setting opcional `infinitepay_webhook_secret` + helper `infinitepay.build_webhook_url(base)` que embute `?s=<secret>` na `webhook_url` enviada à InfinitePay; o endpoint `/api/payments/webhook` valida via `secrets.compare_digest`. Aplicado nos 3 pontos de criação de link (`test-link`, renew, bot trial). Campo adicionado em `Settings.jsx`. 13 novos testes em `tests/test_infinitepay_webhook_real_payload.py`.
- **2026-02**: **Fallbacks robustos para confirmar cliente** — quando o pagamento é aprovado, agora resolvemos o `whatsapp` em cascata (SQLite → Mongo → cache do painel.fun com `extract_whatsapp`), persistindo localmente no primeiro sucesso. Se o template `renewal_success` estiver desabilitado/vazio, enviamos uma **mensagem hardcoded mínima** para o cliente nunca ficar sem confirmação. O alerta admin agora inclui status detalhado: `sim (template)`, `sim (mensagem padrão — template desabilitado)`, `❌ falhou (WhatsApp indisponível)` ou `❌ falhou (sem número no cadastro)`. 5 novos testes em `tests/test_renewal_notification_fallbacks.py`.
- **2026-02**: **🔥 Múltiplos pagamentos no mesmo link agora renovam múltiplas vezes** — idempotência do webhook agora keyed por `transaction_nsu` (único por captura), não por `order_nsu` (mesmo em N pagamentos). Nova coluna `payments.transaction_nsu`. Cada captura no mesmo link do InfinitePay agora dispara nova renovação e nova linha em `payments` (auditoria). Webhook duplicado com mesmo `transaction_nsu` = idempotente. Sem `transaction_nsu` no payload = fallback para idempotência por `order_nsu` (compatibilidade). 5 novos testes em `tests/test_multi_capture_same_link.py`.
- **2026-02**: **Auto-sync tela Clientes com painel.fun** — background loop no `server.py` chama `refresh_cache_task()` a cada 5 min automaticamente. TTL do cache reduzido de 10min → 3min. Frontend polling de 60s → 30s + `refetchOnWindowFocus: true`. `StatusBadge` refatorado para usar o `_status` já computado no backend (Ativo/Vencendo/Vencido) em vez de campo raw. Novo endpoint `GET /api/payments/diagnostics` mostra saúde de settings (admin_whatsapp/public_base_url/handle), estado do template `renewal_success` e últimos 10 pagamentos com WhatsApp+status resolvidos — útil pra diagnosticar por que uma notificação não chegou.
- **2026-02**: **Botão "Reenviar confirmação" na tela Pagamentos + diagnóstico visual** — cada pagamento com status `paid` ganha um botão que chama o novo endpoint `POST /api/payments/resend-notification/{id}`. Esse endpoint faz o mesmo cascade de resolução de phone (SQLite → Mongo → painel cache), persiste o número encontrado, checa se o serviço WA está `ready`, tenta o template `renewal_success` e cai no fallback hardcoded se necessário. **Devolve um JSON detalhado** com cada passo (`sqlite_customers` → `mongo` → `painel_cache`), o phone resolvido, o método usado (template/hardcoded) e o motivo em caso de falha. Frontend abre um modal com o JSON completo. 7 novos testes em `tests/test_resend_notification.py`.
- **2026-02**: **`new_expires_at` sempre populado no template `renewal_success`** — o body do template usa `{name}`, `*{plan_months} mês(es)*` e `até {new_expires_at}`. Agora normalizamos qualquer formato que o painel.fun devolva (`"2027-05-15"`, `"2027-05-15T23:59:59Z"`, unix timestamp) para o padrão brasileiro `dd/mm/aaaa`. Se o painel não retornar data alguma, projetamos localmente: base = `customer.expires_at` (ou hoje, se vencido) + `plan_months × 30d`. O `resend-notification` também busca a data atual do painel cache antes de enviar. O cliente **nunca** mais recebe "ativo até " em branco. 6 novos testes em `tests/test_renewal_message_content.py`.
- **2026-02**: **🔥 Fila de entregas com retry automático a cada 10s + auditoria por mensagem** — nova tabela `notification_deliveries` (id, event_key, phone, body, customer_id, status, attempts, max_attempts, next_retry_at, last_error, sent_at). Novo serviço `services/delivery_queue.py` com `enqueue()` (tentativa imediata + fallback para retry), `_attempt()` e `retry_loop()` (loop background que roda a cada 5s no `server.py`). Novo helper `notifier.send_hardcoded()` para mensagens não-template. `notifier.send_notification()` e `notifier.send_admin_alert()` agora usam a fila — TODAS as notificações (renovação, vencimento, admin alert, trial ready, hardcoded fallback) têm status persistido. Após 5 tentativas falhando, marca como `failed_permanent` + envia alerta direto ao admin (sem loop). Novos endpoints `GET /api/notifications/deliveries` (com filtros por status/customer) e `POST /api/notifications/deliveries/{id}/retry` (força retry imediato via UI). 8 novos testes em `tests/test_delivery_queue.py`.
- **2026-02**: **Sanitização de emoji/4-byte UTF-8 antes de painel.fun** — a MySQL `streamcreed_db` do painel.fun usa `utf8` (3-byte), não `utf8mb4`. Quando o `push_name` do WhatsApp continha emoji (🤍, 😀, 🎉), o create_trial batia em HTTP 400 `"Incorrect string value: '\xF0\x9F...' for column"`. Novo helper `_sanitize_for_painel(s)` em `services/painel.py` filtra codepoints > U+FFFF (todos os emojis) + controles C0/C1/DEL, preservando acentos Latin (é, ã, ç, ñ, ü). Aplicado em `name` e `whatsapp` antes de compor o payload de `create_trial`. Também impõe `max_len` (60 pro nome, 30 pro WhatsApp). 14 novos testes em `tests/test_painel_sanitize.py`.
- **2026-02**: **🚦 Pacing 2min + "digitando..." nas notificações de vencimento** — scheduler agora aguarda `notification_pacing_seconds` (default 120s) entre cada cliente e envia o typing indicator (`chat.sendStateTyping()`) por `notification_typing_ms` (default 4000ms) antes da mensagem. Reduz risco de banimento por spam do WhatsApp. Configuráveis via settings. Node service (`whatsapp-service/index.js`) recebe `typing_ms` no `/send` e faz `sendStateTyping()` + delay antes do `sendMessage()`. 4 novos testes em `tests/test_notification_pacing.py`.
- **2026-02**: **📛 Nome real do cliente em TODAS notificações** — novo `services/name_resolver.py` com cascade SQLite → Mongo → painel.fun cache → fallback. Aplicado no scheduler (vencimentos), `_process_payment_confirmation` (renovação), `/customer/{id}` público (página de pagamento). Nome resolvido é **persistido** automaticamente no SQLite pra próxima renderização ser instantânea. Nunca mais o cliente é chamado de "cliente" quando existe nome real em qualquer fonte. 7 novos testes em `tests/test_name_resolver.py`.
- **2026-02**: **🎁 Desconto same-day no lembrete de 7 dias** — cliente que paga NO MESMO DIA em que recebeu o lembrete `expiration_7d` ganha desconto configurável (%). Se pagar no dia seguinte (6d antes do vencimento), desconto expirado — sem exceções. Admin controla via 2 settings: `discount_7d_enabled` (bool) + `discount_7d_percent` (int, default 5). Novo `services/discount.py` com `get_active_discount(customer_id)` (verifica setting `notified_{cid}_7_{today}` dated) + `apply_discount(cents, pct)`. Wire-in em `create_payment` (renew): desconto aplicado no `amount_cents` + colunas novas `payments.discount_percent` e `payments.original_amount_cents` pra auditoria. Template `expiration_7d` ganhou `{discount_line}` — scheduler injeta "🎁 Pague hoje e ganhe X% de desconto — válido só até o fim do dia!" apenas quando o desconto está ativo. `/customer/{id}` público expõe `active_discount` que a UI PublicPay usa pra mostrar banner verde + preço riscado + preço com desconto em verde. 13 novos testes em `tests/test_discount.py`.
- **2026-02**: **📊 Dashboard turbinado** — atribuição via `?ref={bucket}` (`expiration_7d`, `expiration_3d`, `trial_ready`, `manual`, `direct`) na URL de todo pay_link, gravado em `payments.ref_bucket` (com whitelist anti-injection). Novo endpoint `/api/dashboard/attribution?days=30` (agrupado por bucket + conversion_rate + receita), `/api/dashboard/revenue-by-day?days=14`, `/api/dashboard/balances` (chama painel.fun `get_reseller_balance()` + 2Captcha `res.php?action=getbalance`). Dashboard UI: 2 cards novos (saldo painel + 2Captcha), 2 gráficos novos (BarChart atribuição colorido + BarChart receita/dia), legenda embaixo do gráfico com paid/total/conversion%.
- **2026-02**: **{user} no template renewal_success + Atlas sync + WA autoreconnect** — (a) `_process_payment_confirmation` agora passa `{user}` (=painel_username) no ctx; template `renewal_success` pode usar `{user}` ou `{name}` conforme preferência. (b) `database.set_setting()` espelha automaticamente para MongoDB Atlas via `mongo_store.upsert_setting()`; `notifications.update_notification()` espelha template via `mongo_store.upsert_template()` — best-effort, Atlas caindo não bloqueia local. (c) Node WhatsApp service com `protocolTimeout: 180000` no puppeteer + máquina de reconexão com backoff exponencial (5s → 10s → 30s → 1m → 2m → 5m, reset após `ready`) + watchdog a cada 30s que detecta "silent zombie" (não-conectado por >3min sem `disconnected` event) e força reconnect. Novo endpoint `/reconnect-state` no Node service. 3 novos testes em `tests/test_atlas_sync.py`.
- **2026-02**: **UI + backend polimentos** — (a) Dashboard 2Captcha balance: 2 casas decimais (`$1.23`) em vez de 3 (`$1.234`). (b) `{user}` (painel login) agora está disponível em TODOS os templates (renewal_success + todos expiration_* + trial_ready). Scheduler injeta `ctx["user"] = painel_login` extraído do próprio user do painel.fun. (c) Página Clientes força refresh sincrônico ao abrir: novo query param `?force=true` em `GET /api/painel/users` que aguarda `refresh_cache_task()` completar antes de responder. Frontend chama com `force=true` no `useEffect` de mount (com ref-guard anti-double-fire). Bug fix: TTL do cache reduzido de 180s → 60s. Bug fix bonus: debounce da busca estava usando `useState` no lugar de `useEffect` (nunca disparava). 4 novos testes em `tests/test_force_refresh_and_user_var.py`.
- **2026-02**: **✨ Templates padrão atualizados com `{user}` + botão "Restaurar padrão" + tooltip nas variáveis** — todos os default bodies (`expiration_*`, `expired_*`, `renewal_success`) agora começam com `"Olá {name}! 👋\\n\\nSeu login *{user}* vence..."` pra cliente identificar direto qual conta é. Defaults movidos pra `services/default_templates.py` (fonte única entre init_db e restore). Novo endpoint `POST /api/notifications/{event_key}/restore-defaults` sobrescreve body/title/image_url mantendo `enabled`. Botão "Restaurar padrão" no card de cada template com confirm dialog. Chips de variáveis agora com `title=` tooltip explicando cada uma (`{name}` = nome real, `{user}` = login painel, `{days}` = dias até vencer, etc.) + label "Variáveis disponíveis (clique pra inserir):" acima. Lista de vars expandida em cada evento — inclui `{discount_line}` e `{discount_percent}` no expiration_7d. 4 novos testes em `tests/test_restore_default_template.py`. Suite: 296/296 unit tests verdes.
