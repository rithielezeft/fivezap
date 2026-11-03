# WhatsFlow (fivezap) — PRD

## Original problem
`gh repo clone rithielezeft/fivezap` — import WhatsFlow and run it in preview as-is (no feature/design changes).

## Architecture
- backend/ FastAPI + SQLite (aiosqlite, backend/whatsflow.db) + MongoDB mirror (mongo_store via MONGO_URL)
- whatsapp-service/ Node whatsapp-web.js on :3001, spawned by backend; Chromium at /usr/lib/chromium/chromium; session ~/.whatsflow/wwebjs_auth
- frontend/ React (CRA/craco) dark admin panel
- Integrations: painel.fun (api.controle.fit + 2Captcha), InfinitePay, WhatsApp (real)

## Personas
Reseller admin; end customers (public /teste, /pay/{id}).

## Implemented
- 2026-10-26 Phase 1: repo imported, deps installed (pip, yarn: @phosphor-icons/react, react-globe.gl, three; whatsapp-service node_modules), backend/.env got ADMIN_PASSWORD + JWT_SECRET. Login, all 12 screens, QR code and /teste verified (testing agent 100%). painel.fun sync works (13 users).

- 2026-10-26 Renewal fix (services/painel.py, painel_browser.py): package_id validated vs GET /api/datacomplements (official_duration months), plan_id+amount resolved from price-overrides (title) then /payments/plans (duration_days); browser fallback now sends the real package_id (was hardcoded 17 = 1 month). Read-only verified; no real /renew sent.
- 2026-10-26 Images: uploads saved on local disk (UPLOAD_DIR, default backend/uploads) + mirrored to object storage when EMERGENT_LLM_KEY set; whatsapp_client inlines our /api/uploads/* images as base64 data URI before sending (any host, relative or absolute); Node express json limit 25mb.
- 2026-10-26 Anti-duplicate notifications: delivery_queue atomic claim ('sending' status, inline-attempt vs retry-loop race fixed), WhatsApp service idempotency by delivery id (6h), scheduler single-run lock + key claimed before pacing, auto_coupon key set before send and sweep skipped when template missing. Clientes page: 'Próximo aviso' column, 'Avisos' dialog (programadas/enviadas with WhatsApp-style preview, duplicate warning), 'Testes' filter (GET /api/painel/users/{id}/notifications).
- 2026-10-27 Fila de envio (/fila): live view (3s refresh) of expiration run items (scheduler RUN_STATE), pending/retrying deliveries and scheduled trial reminders, with WhatsApp preview, countdown, filters, cancel selected / cancel all (POST /api/queue/cancel), history; cancelled rows never sent (re-check after pace wait), run cancellations persisted in daily key.
- 2026-10-27 Redesign moderno/minimalista: nova paleta global (#06080D/#0D111A, azul #3B82F6, verde #10B981), sidebar agrupada, página Financeiro (/payments, GET /api/finance/summary) com KPIs, gráficos, renovações por período, top clientes, últimas receitas, tabela filtrável; checkout público /pay mobile-first com barra fixa de total.
- 2026-10-27 Mongo do usuário: mongo_store usa WHATSFLOW_MONGO_URL (+ WHATSFLOW_DB_NAME=whatsflow) quando definido; MONGO_URL/DB_NAME da plataforma intocados.
- 2026-10-27 Sidebar só 'WhatsFlow'; checkout /pay no estilo pagme.xyz (coluna da marca + card branco de planos, cupom, 'Ir para pagamento'), marca configurável (brand_name/brand_logo_url em Configurações); painel 'Qual mensagem gera mais pagamento?' com períodos 7/30/90, funil (enviadas→checkouts→pagos→receita), campeã, ranking com conversão/ticket/participação.
- 2026-10-27 Financeiro: comprovantes por cliente (diálogo), painel de créditos (gastos por plano x custo por crédito configurável, lucro, saldo/última recarga), PDF mensal (reportlab) com download/envio manual e envio automático ao admin_whatsapp (cron platform .emergent/crons.yml dia 1 12:00 UTC + loop horário na Raspberry, idempotente por mês, só dias 1-3). Geografia: Clientes por região (ativos/vencidos/cancelados; cancelado = histórico Atlas/SQLite fora do painel e sem sync há 3+ dias, dedupe por login/telefone).

## Notes
- ADMIN_PASSWORD in .env is re-applied on every backend restart (password changed in UI resets on restart).
- SQLite file and WA session may be lost when the environment resets.

## Backlog
- P0 Phase 2: scan QR, end-to-end trial creation + InfinitePay link test
- P1 Phase 3: owner-requested changes (e.g. Dashboard "Clientes ativos" counts local table, shows 0 vs 13 painel users)

## 2026-06 — Filtro "Notificar vencidos" + correções
- Diálogo "Notificar vencidos" com filtro Todos / Só testes / Só regulares (contagens, selo "Teste", seleção por filtro). API: GET /api/painel/expired retorna is_trial, count_trial, count_regular; POST /api/painel/notify-expired aceita kind (all|trial|regular) quando user_ids vazio.
- Geografia: busca por cliente seleciona a região e a aba do status do cliente; clique manual na aba é respeitado.
- Saldo do painel confirmado em créditos (currency=CREDITS). Pluralização "fatura/faturas".
- Pagamentos TESTR_ já não existem no banco.
- Backlog: test_delivery_dedup::test_send_hardcoded_no_dedup falha (já falhava antes, não relacionado).
- 2026-10-27: Raspberry: requirements-pi.txt (deps mínimas), update.sh rebuilda frontend se src mais novo que build (ou FORCE_REBUILD=1). Prévia de links (og:title/description/image) — "Pagamento seguro e liberação na hora" + /og-image.jpg (terno). DNS whatsflow.zeferius.com ainda apontando para Hostinger (usuário precisa ajustar A → 187.121.232.128).
- 2026-10-27: 'Testar conexão' (POST /api/painel/test-connection {username,password}) usa as credenciais digitadas no formulário; cache de token do painel agora é por usuário+senha (troca de usuário salva força novo login).

## 2026-10-28 — Mercado Pago + contas múltiplas + vários pontos + adulto
- services/payment_accounts.py (setting `payment_accounts` JSON; legado infinitepay_handle vira conta "default" se nunca salvo). Roteamento: 1ª conta ativa abaixo do limite mensal; todas cheias → última. MP repassa 0,99% (round).
- services/mercadopago.py (Pix /v1/payments, httpx). Endpoints públicos: GET /api/payments/mp-status/{id}, POST /api/payments/mp-webhook. Admin: /api/payment-accounts (GET/PUT, POST /{id}/test).
- Pagamento com vários pontos (mesmo WhatsApp) → extra_customer_ids, renovados após o principal (_renew_extra_accounts). Canal adulto: renew_user(adult=) mapeia pacotes 17/42/55/57 ↔ 18/43/56/58 + adult_channels.
- {password} no template renewal_success. linkPreview:true no whatsapp-service. paid_renewal_failed conta como recebido.
- payments_sync: guarda de status por rank + bulk_write + refresh local quando Mongo avança.
- Não testado ao vivo: cobrança real Mercado Pago (precisa Access Token do usuário em Configurações → Pagamento → Contas).

## 2026-10-28 — Trevo da Sorte + números BR
- phone_extractor.br_canonical/br_variants: celular BR sempre com 9º dígito (553186582251 → 5531986582251); usado em _clean, bot.normalize_phone, real_phone (LID), /api/public/trial (valida 12–15 dígitos) e find_or_create_customer (casa variantes e atualiza linha antiga).
- services/raffle.py + routers/raffle.py: trevos (payments.clovers) = cupons do mês pagos; coringa = 1 participante; sorteio automático último dia do mês 20h (loop 10 min) ou "Sortear agora"; lock no Mongo raffle_draws (_id=YYYY-MM); prêmio renova o ganhador (painel) + WhatsApp + alerta admin. Página /sorteio (DrawReel do sortezeferius). Pay page: CloverPicker (marcado por padrão, +/−, desmarcável).
- Settings: raffle_enabled, raffle_clover_price, raffle_prize_months, raffle_joker_login.

## 2026-10-28 — Coringas, página pública /trevo, Configurações em seções
- Coringas: raffle_joker_count (0–50) + raffle_joker_phone; sempre rotulados "Coringa N" (decisão ética: não disfarçar como clientes reais). Coringa vencedor renova raffle_joker_login se definido; aviso ao WhatsApp padrão.
- Página pública /trevo (PublicRaffle.jsx): contagem regressiva (America/Sao_Paulo), participantes com nome mascarado (3 letras + ***), histórico + replay DrawReel. GET /api/public/raffle retorna entries/history mascarados.
- Settings.jsx: menu lateral por seções (Painel, 2Captcha, Pagamentos, Descontos, Notificações, Sistema, Guia).
- Financeiro: filtro "🍀 Com trevo", selo por pagamento e total. Variáveis {clovers} e {clover_coupons} em renewal_success (todas as rotas de envio).
- Nota testes: tests/test_phone_br_and_raffle.py::test_perform_draw_mocked passa sozinho; falha só quando rodado junto com outros testes de sorteio (estado compartilhado entre testes).

## 2026-10-29 — Preferências por cliente + alerta admin detalhado
- services/customer_prefs.py (Mongo `customer_prefs`, cache 60s): prices por plano, fixed_plan, no_discount, notify_events (None = todos). API admin GET/PUT /api/customer-prefs/{painel_id}. Dialog "Preço" em Clientes (CustomerPrefsDialog.jsx).
- Aplicado em: create_payment (preço por login, plano fixo, extras com preço/desconto próprios), página /pay (planos filtrados, cupom oculto, total por login), coupon/discount/auto_coupon (bloqueio), scheduler + upcoming (lembretes escolhidos).
- Alerta "Pagamento confirmado" ao admin: forma de pagamento + conta, nº de logins, trevo (sim/não + qtd), desconto/cupom.
- Raffle: usuário colou NOMES_COMUNS em routers/raffle.py (nomes comuns para coringas no público) — agente recusou ampliar/contar coringas como clientes; não reverteu o código do usuário.


## [IMPORT 2026-06] Branch fivezap3 imported into Emergent preview (as-is)
- Code from rithielezeft/fivezap@fivezap3 (108471d). Startup fixes only: installed deps; pydantic pin 2.9.2 -> 2.14.2 (conflicted with google-genai in requirements.txt); ADMIN_PASSWORD + JWT_SECRET in backend/.env; fresh SQLite DB.
- Verified iteration_16: login, 14 admin pages, /teste, /pay/{id}, /trevo, WhatsApp QR.
- Reported, not fixed: dashboard customer counts use empty local table; parallel 2Captcha solves at startup + key in logs; /api/settings 401 on /login.

- [2026-06] Connected to user Atlas via WHATSFLOW_MONGO_URL / WHATSFLOW_DB_NAME (whatsflow) secrets; JWT_SECRET replaced with user value. Saved URL query is truncated (retryWrites=tru>), mongo_store._clean_url repairs it. Atlas shared with Raspberry/prod (1223 customers, 468 payments).

- [2026-06] Raffle rounds: raffle_state (Mongo) round-based instead of month; new round starts at previous draw time; settings auto_restart/auto_renew; manual entries (raffle_manual_entries) add/remove; POST /api/raffle/new-round. Tested iteration_17.
