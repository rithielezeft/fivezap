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

## Notes
- ADMIN_PASSWORD in .env is re-applied on every backend restart (password changed in UI resets on restart).
- SQLite file and WA session may be lost when the environment resets.

## Backlog
- P0 Phase 2: scan QR, end-to-end trial creation + InfinitePay link test
- P1 Phase 3: owner-requested changes (e.g. Dashboard "Clientes ativos" counts local table, shows 0 vs 13 painel users)
