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

## Notes
- ADMIN_PASSWORD in .env is re-applied on every backend restart (password changed in UI resets on restart).
- SQLite file and WA session may be lost when the environment resets.

## Backlog
- P0 Phase 2: scan QR, end-to-end trial creation + InfinitePay link test
- P1 Phase 3: owner-requested changes (e.g. Dashboard "Clientes ativos" counts local table, shows 0 vs 13 painel users)
