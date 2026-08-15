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


## [FEATURE 2026-02-28] Playbook visual em Configurações

Novo card no topo da tela de Configurações que **mapeia cada rotina do app pras settings que a alimentam**. Objetivo: evitar mudanças acidentais (ex: "mexi no `discount_7d_percent` sem saber que o cupom VOLTA também usa").

**Como funciona:**
- Card "🗺️ Como cada configuração é usada" com 6 fluxos, cada um com ícone colorido, título, descrição curta e chips clicáveis com os keys das settings envolvidas.
- Clicar num chip **rola a página até o campo** e ativa uma classe CSS `.setting-highlight` que adiciona um anel verde por 2 segundos.
- Chip com marcação `⚡` (ex: `discount_7d_percent`) sinaliza settings **compartilhadas** entre múltiplos fluxos.

**Fluxos mapeados:**
1. 🔔 **Lembretes de vencimento** — `notification_days`, `display_timezone`, `admin_whatsapp`, `dedup_window_minutes`
2. 🏷️ **Desconto 7d & Cupom VOLTA automático** — `discount_7d_enabled`, `discount_7d_percent` (⚡ compartilhado)
3. ⚡ **Anti-duplicação de mensagens** — `dedup_enabled`, `dedup_window_minutes`
4. 🎫 **Testes (trials)** — `trial_package_id`
5. 🔄 **Sincronia com painel.fun** — `painel_refresh_interval_seconds`, `twocaptcha_key`, `painel_username`, `painel_password`
6. 💳 **Pagamentos & Preços** — `infinitepay_handle`, `plan_price_1m/3m/6m/12m`, `infinitepay_webhook_secret`

**Implementação técnica:**
- `pages/Settings.jsx`: array `FLOWS` + função `scrollToSetting(key)` que faz `scrollIntoView({behavior: "smooth", block: "center"})` + adiciona `.setting-highlight` por 2s.
- `index.css`: nova classe com `box-shadow: 0 0 0 3px rgba(52, 199, 89, 0.6)` + `border-color` verde.
- Ícones do Phosphor: MapTrifold (título), Bell, Tag, Lightning, Ticket, ArrowsClockwise, CreditCard.

**Smoke-test**: playbook renderizou 6 fluxos com 19 chips totais; clicar em `discount_7d_percent` scrollou até o campo InfinitePay & Preços com anel verde visível. Zero lint errors.



## [FIX 2026-02-28] Auto-cupom usa a mesma % do desconto 7d

**Pedido do usuário**: "a porcentagem dos cupom de volta tem que ser o mesmo que é o Desconto no lembrete 7d — % que já está configurado só deve usar o mesmo".

**Correção em `services/auto_coupon.py::sweep_once`**: removida a leitura da setting `auto_coupon_percent`. Agora lê **`discount_7d_percent`** (a mesma que o desconto do lembrete de 7 dias usa em `services/discount.py`).

Fallback: 15% se a setting estiver vazia/inválida. Docstring atualizada pra deixar claro o single source of truth.

**Efeito prático**: se o admin ajustar "Desconto do lembrete 7d — %" para 8%, o próximo cupom `VOLTA` gerado automaticamente vem com 8% também. Zero configuração duplicada.

Verificação: `_get_float("discount_7d_percent", 15.0)` retorna o valor correto do DB (testado com curl no endpoint de settings + inspeção direta). Regressão: 30 testes de cupom/dedup/geo/uploads continuam passando.



## [FIX 2026-02-28] Formato bonito de data + VOLTA aleatório + guia deploy

### 1) `formatDateShort` — formato compacto para cards
- Novo helper em `lib/api.js`: `formatDateShort(iso)` retorna `08-08-26 às 23:08h` (dia-mês-ano curto + hora com "às" e "h" no final)
- Aplicado em `Coupons.jsx`: no `⏱️ Expira`, no `createdAt` do card, e nos `used_at` do dialog de usos
- Fuso respeita `_displayTz` (América/São_Paulo default). `formatDateBR` continua existindo para lugares onde a granularidade completa faz sentido (histórico de pagamento, etc)

### 2) Auto-Cupom com código aleatório (não mais derivado)
- `services/auto_coupon.py::_create_personal_coupon` agora gera código no formato `VOLTA` + **6 chars aleatórios** do alfabeto `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (sem 0/O/1/I ambíguos)
- 10 tentativas de retry contra colisão na constraint UNIQUE
- Idempotência preservada via setting `auto_coupon_sent_{customer_id}` (já existia)
- **Vantagem**: cliente não consegue deduzir o cupom do amigo pelo próprio ID; admins podem compartilhar códigos sem vazar informação de conta

### 3) Guia de deploy pro Raspberry Pi
- Já existe script `/app/update.sh` (304 linhas, idempotente, com backup + rollback automático). Fluxo do admin:
  ```bash
  cd ~/WhatsFlow && sudo bash update.sh
  ```
- O script faz: backup DB+.env → para backend → pull do GitHub → reinstala deps Python/Node → rebuild frontend se mudou → restart supervisor → health-check → rollback automático se falhar



## [FEATURES 2026-02-28] API Docs Page + Auto-Coupon + Cupom v2

### 1) Página de Documentação da API (`/documentacao`)

- Nova página que consome `/api/openapi.json` da FastAPI e renderiza **80 endpoints organizados em 17 grupos** com:
  - Badge de método colorido (GET verde, POST azul, PUT laranja, DELETE vermelho, PATCH roxo)
  - Path com syntax highlighting monoespaçado
  - Summary + description do endpoint
  - Botão "copiar curl" (📋) com o Bearer token pré-preenchido
  - Busca por método/path/summary
  - Link "Abrir Swagger completo ↗" pra visão detalhada
- FastAPI agora expõe `openapi_url="/api/openapi.json"`, `docs_url="/api/docs"`, `redoc_url="/api/redoc"` (mudança do default `/openapi.json` porque o ingress só roteia `/api/*` pro backend)
- Auth: `/api/openapi.json`, `/api/docs`, `/api/redoc` marcados como públicos (spec não expõe dados sensíveis)
- Sidebar: novo link "API" com ícone Code

### 2) Auto-Cupom para clientes vencidos (3+ dias)

Nova `services/auto_coupon.py` — loop de hora em hora:
- Filtra painel users com `status='expired'` e `days_since_expiry >= 3` (config `auto_coupon_expired_days`)
- Pula trials (`package_id == trial_package_id`)
- Cria cupom personalizado `VOLTA{customer_id_last6}` com:
  - **15% off** (config `auto_coupon_percent`, aceita decimais)
  - **Expira em 24h** (config `auto_coupon_ttl_hours`)
  - **1 uso máximo** (config `auto_coupon_max_uses`)
- Envia via WhatsApp usando template `auto_recovery_coupon` com `{coupon_code}`, `{discount_percent}`, `{expires_in_hours}`, `{pay_link}`, `{days_expired}`, `{name}`
- **Idempotente**: setting `auto_coupon_sent_{customer_id}` garante 1x por cliente pra sempre
- Registrado no lifespan do `server.py` com cancel no shutdown
- Toggle global: setting `auto_coupon_enabled` (default true)

### 3) Cupom v2 — expiração + max_uses + decimais

**Backend (`services/coupon.py` + `routers/coupons.py`):**
- `discount_percent` agora é **float** (`REAL` em SQLite) — aceita **12.3%**, **7.5%**, etc. Cap ainda em 50%. `clamp_percent` retorna 0 para valores <= 0 (caller decide)
- Novo campo `expires_at` (ISO datetime, nullable) — hard cap de tempo no cupom
- Novo campo `max_uses` (int, nullable) — total de resgates permitidos (COUNT de `coupon_usages WHERE coupon_id = ?`)
- `CouponCreate` novo campo `auto_expire_24h: bool` — se true e `expires_at` vazio, backend seta automaticamente para +24h
- `validate_coupon` agora verifica em ordem: vazio → não encontrado → inativo → **expirado** → **esgotado** → cooldown 28d → OK

**Frontend (`pages/Coupons.jsx`):**
- Input `type="number"` com `step={0.1}` para % (aceita decimais)
- Novo `datetime-local` input "Expira em"
- Novo input "Máx. usos"
- Switch "Expirar em 24h automaticamente" (só no create)
- Cards mostram `⏱️ Expira: DD/MM/YYYY HH:mm` e `🎯 Usos: X / Y` quando aplicável

**Migrações** em `database.py`: 2 novas colunas em `coupons` (`expires_at TEXT`, `max_uses INTEGER`).

**Testes:** todos os 49 testes existentes de cupom/dedup/scheduler continuam passando. `clamp_percent` teste atualizado para novo comportamento float.



## [FEATURE + FIX 2026-02-28] Grupos/Canais WhatsApp + Dedup por body_hash + Pacer global

### Parte 1 — 6 novos endpoints para Grupos/Canais

**Node service (`whatsapp-service/index.js`):**
- Novo `GET /chats?type=group|newsletter` — lista todos os chats do tipo pedido com `id`, `name`, `is_group`, `is_newsletter`, `participants_count`, `unread_count`.
- `/send` agora aceita JIDs `@newsletter` e `@broadcast` (além dos já existentes `@lid`, `@c.us`, `@g.us`).

**Backend (`routers/whatsapp.py`):**
- `GET /api/whatsapp/groups` — lista grupos
- `GET /api/whatsapp/channels` — lista canais
- `POST /api/whatsapp/groups/send` — envia texto/imagem para grupo (chat_id `@g.us` obrigatório)
- `POST /api/whatsapp/channels/send` — envia texto/imagem para canal (chat_id `@newsletter` obrigatório)
- `POST /api/whatsapp/groups/send-image` — send-image explícito (image_url obrigatório) para grupo
- `POST /api/whatsapp/channels/send-image` — mesmo para canal
- Tratamento gracioso quando WA não está pronto: retorna `{chats: [], count: 0, not_ready: true, message: "..."}` com HTTP 200 (evita 502 do Cloudflare)

**Client (`services/whatsapp_client.py`):** adicionado `list_chats(chat_type)`.

### Parte 2 — Fix definitivo da duplicação de notificações

**Bug reportado**: "duplicação rápida de todas notificações e o disparo rápido da fila de vencimento e vencendo, precisa ter um tempo entre cada disparo".

**Causa raiz**: o dedup atual só olhava `(phone, event_key)`. Se duas rotas diferentes (ex: scheduler + botão manual, ou dois event_keys distintos que renderizam a mesma mensagem) enfileiravam ao mesmo tempo, ambos passavam. E o loop de retry disparava até 50 mensagens seguidas sem pausa → burst → WA detecta anti-spam.

**Correções em `services/delivery_queue.py`:**

1. **Body-hash dedup (nova rede de segurança)**:
   - Adicionada coluna `body_hash` em `notification_deliveries` (sha256 de `phone|body[:500]|image_url`).
   - Nova setting `body_dedup_window_minutes` (default **15**).
   - No `enqueue()`, se `dedup_enabled` estiver on: primeiro tenta `(phone, event_key)` (como antes), depois **body_hash** dentro da janela. Um hit no body_hash faz LOG explícito com `prev_event=...` pra debugar.
   - Setando `body_dedup_window_minutes=0` desativa.

2. **Pacer global entre sends**:
   - Nova função `_wait_for_pace_slot()` — usa `asyncio.Lock` global + `time.monotonic()` pra garantir que nenhum WA send acontece sem esperar `send_min_gap_seconds` (default **3s**) desde o último.
   - Chamada no `_attempt()` **imediatamente antes** do `whatsapp_client.send_message()`, então TODOS os caminhos (envio inicial + retry loop) respeitam o gap.
   - Setando `send_min_gap_seconds=0` desativa.

**Testes de regressão** (`tests/test_delivery_dedup_v2.py`, 5 casos, todos passando):
- `test_hash_body_stable_and_normalized` — hash reproducível, sensível a phone/body/image
- `test_dedup_by_body_hash_across_event_keys` — 2 enqueues com event_keys DIFERENTES mas body igual → só 1 send real
- `test_dedup_body_hash_disabled_when_window_zero` — setting=0 desliga
- `test_wait_for_pace_slot_enforces_min_gap` — 3 chamadas com gap=0.5s levam ≥0.9s totais
- `test_wait_for_pace_slot_no_wait_when_gap_zero` — gap=0 é instantâneo

**Configurações novas** (Settings): `body_dedup_window_minutes` (15), `send_min_gap_seconds` (3). Podem ser ajustadas via `set_setting` ou pela tela de Settings.



## [FEATURE 2026-02-28] Mapa 3D — Geografia dos Clientes (P0 — CONCLUÍDO)

Nova página `/geografia` que mostra a distribuição geográfica dos clientes num **globo 3D interativo** com marcadores por país e drill-down para o Brasil (por DDD).

**Backend:**
- `services/geography.py` — mapeamentos:
  - **DDI → país** com longest-prefix match (351 vence 3, 55 vence 5). Cobre 30+ países comuns em bases brasileiras (Américas, Europa, África, Ásia/Oceania)
  - **DDD (BR) → estado/região** com todas as 66 áreas de DDD válidas + lat/lng aproximados das capitais
- Novo `routers/analytics.py` — `GET /api/analytics/geography?scope=all|active|expired`:
  - Fonte primária: cache do painel (source of truth), fallback pra tabela `customers` local
  - Filtro `scope` respeita status calculado (`compute_expiration_info`)
  - Retorna `by_country`, `by_br_state`, `total`, `top_country`, `unresolved`, `no_phone`

**Frontend:**
- Instalado `react-globe.gl` + `three` (via yarn)
- Nova página `/geografia` (`pages/Geography.jsx`):
  - Globo 3D com textura earth-dark, atmosfera azul, marcadores dimensionados por count
  - **Auto-focus** e pulsing ring no `top_country` (Brasil no caso)
  - Auto-rotate suave (`autoRotateSpeed=0.4`)
  - **Tooltip com bandeira + contagem** ao passar o mouse
  - Painel lateral com 2 seções: "Por país" (ordenado) e "Brasil por DDD" (colapsável, com scroll até 420px)
  - Toggle de scope (Todos / Ativos / Expirados) no header
  - Aviso de "não mapeados" quando há clientes sem telefone ou com DDI desconhecido
- `App.js` — rota `/geografia`
- `Sidebar.jsx` — novo link "Geografia" com ícone `Globe`

**Testes:** 12 casos em `tests/test_geography.py`, todos passando (resolução BR/ES/PT/US, longest-prefix, retornos None para inválidos, formato das constantes)

**Smoke-test end-to-end**: página renderizou 164 clientes → 4 países + 43 regiões BR. Top: BR (161) · Espanha, UK, PT (1 cada). Top BR: SP-Capital (27), Campinas (15), Juiz de Fora (12), Porto Alegre (8), RJ (7), Curitiba (6), Joinville (6).



## [FIX 2026-02-28 P0] Upload de imagem "Token inválido"

**Bug reportado**: "na pagina de comando apareceu erro novamente ao tentar fazer upload de imagem Falha ao enviar imagem: Token inválido"

**Root cause**: em `frontend/src/pages/Templates.jsx::handleImageUpload`, eu chamava `localStorage.getItem("token")` — mas o token JWT é armazenado como **`wf_token`** (ver `lib/api.js:13` e `Login.jsx:28`). Chave errada → token era `null` → backend rejeitava com `Token inválido`.

**Correção**: `Templates.jsx` agora usa o helper `uploadsApi.upload()` de `lib/api.js`, que passa pela mesma instância axios usada em toda a app (com interceptor que injeta o `Bearer wf_token` automaticamente). Um único source-of-truth para autenticação.

- Removido o `fetch()` manual + montagem de header customizado.
- Grep confirmou que não há outros locais no frontend usando `localStorage.getItem("token")` incorretamente.


## [FIX 2026-02-28 P0] Trials recebiam notificação de vencimento + upload de imagem falhando

**Bugs reportados:**
1. "notificações de vencimento começou a ser enviado para os clientes trial de testes"
2. "quando tento adicionar imagem para upload nos comandos aparece Falha ao enviar imagem"

**Root cause #1** — `services/scheduler.py::_check_and_notify()` iterava TODOS os `painel.list_users()` sem filtrar. Clientes com `package_id=61` (trial) recebiam mensagens `expiration_3d/1d/0d` além do fluxo próprio deles (`trial_1h_reminder`, `trial_expired`). Resultado: cliente em teste recebia "Seu plano vence em 3 dias!" enquanto o trial ainda estava rodando.

**Root cause #2** — dois fatores combinados:
- Backend: `MAX_SIZE_MB=5` era muito baixo (fotos de celular passam disso), e extensões HEIC/HEIF (iPhone default) não estavam permitidas.
- Frontend: `Templates.jsx::handleImageUpload` fazia `res.json()` sem checar `res.ok`. Se o servidor retornava 413/400 com `{"detail": "..."}`, o `data?.path` era undefined → mostrava toast genérico "Falha ao enviar imagem" sem revelar o motivo real.

**Correções:**

- **`services/scheduler.py`**: novo filtro no início do loop — lê `trial_package_id` das settings (default 61) e pula qualquer painel user cujo `package_id`/`current_package_id` == trial_pkg, OU `is_trial=True`, OU `type`/`group` contém "trial".

- **`routers/painel_users.py::notify_expired`**: mesmo filtro adicionado. Quando admin clica "Notificar Vencidos" sem selecionar IDs específicos, trials são pulados automaticamente (`skipped_trial` no retorno). Se selecionar um trial explicitamente pelo checkbox, ainda é enviado (controle do admin preserved).

- **`routers/uploads.py`**:
  - `MAX_SIZE_MB` **5 → 15** (aceita fotos raw de celular)
  - `ALLOWED_EXT` agora inclui **heic, heif, bmp** (além de jpg/jpeg/png/gif/webp)
  - Mensagens de erro amigáveis: `"Imagem tem X.XMB — o limite é 15MB"` e `"Extensão .heic não permitida. Use: ..."` em vez de mensagens genéricas

- **`frontend/pages/Templates.jsx`**: `handleImageUpload` agora checa `res.ok` e mostra o `data.detail` do servidor no toast — o admin vê a razão real ("Imagem tem 8.3MB — limite é 15MB") em vez de "Falha ao enviar imagem".

**Testes de regressão** (`tests/test_scheduler_trial_skip_and_uploads.py`, 3 casos, todos passando):
- `test_scheduler_skips_trial_package` — sistema com 3 painel users (trial + regular + far-future); apenas o regular expirando em 3 dias recebe notificação.
- `test_scheduler_skips_is_trial_flag` — quando painel expõe `is_trial=true` em vez de `package_id`, também é pulado.
- `test_upload_extension_and_size` — trava heic/heif/bmp aceitos + limite >=10MB.



## [FIX 2026-02-28 P0] Duplicação de lembretes 1h/3h + ERROR_NO_SLOT_AVAILABLE

**Bugs reportados**:
1. "Duplicação nas mensagens de teste vencendo 1h e 3h e em notificações de vencimento"
2. `ERROR_NO_SLOT_AVAILABLE` — cliente paga mas painel.fun rejeita renovação, admin precisa renovar manualmente

**Root cause #1** — `services/reminders.py::schedule()`: fazia `INSERT` cego, sem checar se já existia um pendente `(phone, event_key, sent=0)`. Se o cliente enviasse o comando de teste 2x (dedup do bot é só 30s) OU se o trial fosse criado por 2 fluxos diferentes (bot + form público), agendava 2 lembretes por evento → 4 mensagens totais.

**Root cause #2** — `_process_payment_confirmation`: ao falhar `painel.renew_user`, apenas marcava `paid_renewal_failed` e alertava admin. Não retry. Cliente ficava sem renovar mesmo tendo pago.

**Correções:**

- **`services/reminders.py::schedule()`**: agora faz **upsert por `(phone, event_key, sent=0)`**. Se já existe pendente, atualiza `send_at` + `context` em vez de inserir duplicata. Isso resolve automaticamente para AMBOS os call sites (bot.py e trial_flow.py).

- **`routers/payments.py`** (bloco de exception da renovação):
  - Classifica erro como **transitório** (`NO_SLOT_AVAILABLE`, `TIMEOUT`, `502/503/504`, `CONNECTION`) ou permanente.
  - Se transitório: agenda auto-retry usando campos novos em `payments`: `renewal_attempts`, `renewal_next_retry_at`, `renewal_last_error`. Backoff: **5min, 15min, 30min, 1h, 4h, 12h** (6 tentativas em ~19h).
  - Envia **mensagem amigável ao cliente** no primeiro erro: "Recebemos seu pagamento, estamos ativando..." — antes o cliente ficava no escuro.
  - Alerta ao admin agora mostra **guidance específica** por tipo de erro (sem vaga, transitório, permanente) e o número da tentativa.

- **Novo `services/renewal_retry.py`** — background loop (60s) que:
  1. Busca pagamentos `paid_renewal_failed` com `renewal_next_retry_at <= now`
  2. Chama `painel.renew_user` novamente
  3. **Sucesso**: marca `paid`, envia `renewal_success` (que falhou originalmente) + fallback hardcoded se template desabilitado, alerta admin de sucesso, atualiza Mongo
  4. **Falha persistente**: bumpa attempts, reagenda próximo retry
  5. **Após 6 falhas**: para de tentar, alerta admin critical "🛑 Renovação desistida"

- **Migrações em `database.py`**: adicionadas 3 colunas nulas em `payments` (`renewal_attempts`, `renewal_next_retry_at`, `renewal_last_error`).

- **`server.py`**: registrado `renewal_retry_loop` no lifespan (com `task_renewal_retry.cancel()` no shutdown).

**Testes de regressão** (`tests/test_reminders_and_retry.py`, 7 casos, todos passando):
- 4 casos de reminder dedup: mesmo (phone, event_key) dedupe, event_keys diferentes não dedup, phones diferentes não dedup, após `sent=1` cria novo row.
- 3 casos de retry loop: recuperação com sucesso (status→paid + notificação), reagenda em falha continuada com backoff correto (~15min), desiste após 6 tentativas com alerta admin de "DESISTIDA".

**Efeito prático**:
- Cliente não recebe mais lembrete duplicado de teste.
- `ERROR_NO_SLOT_AVAILABLE` agora auto-recupera na maioria dos casos (retry em 5min geralmente resolve).
- Admin só precisa agir manualmente após 19h de tentativas falhando.
- Cliente recebe mensagem amigável ("pagamento recebido, estamos ativando") em vez de silêncio.



## [FIX 2026-02-28 P0] Lembretes disparando no dia errado (bug de fuso)

**Bug reportado**: "Agendamento dos lembretes ainda não foi arrumado".

**Root cause** em `services/expiration.py:75`:
```python
days = (exp_dt.date() - now.date()).days
```
Ambos `exp_dt` e `now` são UTC. Como São Paulo é UTC-3, todo dia entre **21:00 e 23:59 SP** o UTC já rolou pro dia seguinte. Resultado: quando o plano vence em data cuja hora UTC está no dia SEGUINTE (ex: `22:00 SP dia X` = `01:00 UTC dia X+1`), o cálculo faz `(X+1) - Y` em vez de `X - Y` → produz **1 dia a mais**. Lembretes de "3 dias antes" acabavam disparando no que ainda era o "4º dia antes" pro cliente no fuso SP → mensagem chega **~24h antes** do horário certo.

Além disso, o `dedup_key` (`notified_{user}_{days}_{now.date()}`) também usava `now.date()` em UTC — a chave rolava à meia-noite UTC (21:00 SP), então o mesmo lembrete podia disparar 2x no mesmo dia local.

**Correções aplicadas:**

- **`services/expiration.py`**: `compute_expiration_info(user, tz=None)` agora aceita fuso opcional (default `America/Sao_Paulo`). O cálculo faz `exp_dt.astimezone(tz).date() - now.astimezone(tz).date()`, comparando **datas locais do admin**.
- **`services/scheduler.py`**:
  - Nova função `_get_display_tz()` que lê `display_timezone` das settings.
  - Passa o fuso para `compute_expiration_info(u, tz=display_tz)`.
  - `dedup_key` agora usa `now_local.date().isoformat()` (dia SP), não UTC.
  - `today_start` para checar deliveries do dia usa `today_start_local.astimezone(utc)`.
  - `expires_at` no contexto do template formatado em SP: `exp_dt.astimezone(display_tz).strftime("%d/%m/%Y")` — antes vinha em UTC (podia mostrar `03/03` para um plano que vence `02/03 22:00 SP`).

**Testes de regressão** (`tests/test_scheduler_timezone.py`, 4 casos, todos passando):
- `test_days_at_late_evening_sp_uses_local_calendar_day` — 23:00 SP, plano expira SP-tz vs UTC-tz, valida que o cálculo usa dia SP.
- `test_days_at_early_morning_sp_is_same_as_utc_day` — sanity: caso normal (10:00 SP) continua funcionando.
- `test_days_exactly_at_midnight_utc_before_midnight_sp` — o cenário exato do bug: expiração `22:00 SP` vs current `20:00 SP` 3 dias antes → SP retorna 3d (correto), UTC retornaria 4d (bug antigo).
- `test_days_calculation_symmetric_across_utc_dst_free_zones` — passando `tz=timezone.utc` explicitamente reproduz o bug antigo, provando que o parâmetro funciona.



## [FIX 2026-02-28 P0 (v2)] Correção da correção — LID sendo salvo como telefone falso

**Bug reportado pelo usuário**: o cliente foi registrado com o número `+191134936608840` — que é o próprio LID (15 dígitos, não é telefone real).

**Root cause da regressão**: minha correção anterior fazia fallback para `contact.id.user` quando `contact.number` era null. Mas para chats LID, o `contact.id.user` **É** o LID em si (não um telefone). Resultado: `real_phone = "191134936608840"` foi salvo como o telefone do cliente e enviado ao painel.

**Pesquisa (web search)**: a documentação do whatsapp-web.js confirma que `contact.number === null` é o comportamento esperado para contatos LID-only por design de privacidade — **não é possível resolver LID→telefone de forma garantida**. Existe uma API mais nova (`client.getContactLidAndPhone`) que às vezes traz o telefone quando o WhatsApp permite.

**Correções aplicadas:**

- **Node service (`whatsapp-service/index.js`)**:
  - Aceita apenas `contact.number` (o telefone real). Removido o fallback para `contact.id.user`.
  - Adiciona validação de formato: só aceita se tiver **8-14 dígitos** (E.164 real é até 15, mas LIDs geralmente têm 15-18+ dígitos, então 14 é um teto conservador).
  - Tenta `client.getContactLidAndPhone([lid])` como último recurso — a API documentada que às vezes mapeia LID→telefone.

- **Backend (`services/bot.py`)**: validação defensiva idêntica — se o `real_phone` recebido tiver <8 ou >14 dígitos, rejeita silenciosamente (log de warning) e NÃO faz backfill em `customers.whatsapp`.

**Resultado**: para clientes com LID estrito onde o WhatsApp não expõe o telefone, o painel não recebe mais um número falso — apenas fica sem o número no `reseller_notes` (que é a degradação correta). Para clientes onde `contact.number` retorna o telefone real, o fluxo continua funcionando.

**Testes de regressão** (`tests/test_lid_real_phone.py`, agora 5 casos, todos passando):
- Adicionado: `test_incoming_lid_rejects_lid_shaped_real_phone` — simula exatamente o cenário do usuário (LID de 15 dígitos vindo como `real_phone`). Assert que o customer.whatsapp **NÃO** fica com o LID.



## [FIX 2026-02-28 P0] Número do cliente LID não registrado no painel.fun

**Bug reportado pelo usuário**: "Colega enviou o comando de teste e o número dele NÃO foi registrado automaticamente".

**Root cause**: para usuários no protocolo de privacidade LID do WhatsApp (comunidades, contas Business, alguns celulares novos), o JID chega como `123456789@lid` — sem o número real. O `bot.py:_run_trial_creation` fazia `whatsapp=phone_clean if not phone_clean.endswith("@lid") else ""` → mandava **string vazia** para `painel.create_trial` → `reseller_notes` nunca era setado.

**Correções:**

- **`whatsapp-service/index.js`**: para cada mensagem recebida, extrai o telefone real via `contact.number` (fallback: `msg._data?.senderPn`, `contact.id.user`) e envia como campo `real_phone` no webhook para o backend.
- **`routers/whatsapp.py`**: `IncomingPayload` aceita `real_phone: Optional[str]`.
- **`services/bot.py::process_incoming_message`**: se `phone_clean.endswith("@lid")` e `real_phone` foi resolvido, faz backfill em `customers.whatsapp` (só a primeira vez ou quando muda) — assim o admin vê o número real na UI também.
- **`services/bot.py::_run_trial_creation`**: reconstroi `whatsapp_for_painel` — para LID, usa `customer.whatsapp` (que agora tem o número real) e ignora se ainda for LID puro. Manda para `painel.create_trial` → `reseller_notes = "+{whatsapp}"` ✅.

**Testes de regressão** (`tests/test_lid_real_phone.py`, 4 casos, todos passando):
1. `test_incoming_lid_backfills_real_phone_on_customer` — Node manda `real_phone`, customer row acaba com o telefone real em `whatsapp`.
2. `test_incoming_non_lid_does_not_overwrite_whatsapp` — para chats normais (não-LID), o `real_phone` não sobrescreve o número que já é o próprio JID.
3. `test_run_trial_creation_sends_real_phone_to_painel_for_lid` — assert-chave: `painel.create_trial(whatsapp="5511911223344")` para LID com telefone real resolvido.
4. `test_run_trial_creation_lid_without_real_phone_sends_empty` — degradação graciosa: se Node não conseguir resolver, manda `whatsapp=""` (sem crash, sem LID falso).



## [FIX 2026-02-27 P0] Duplicação de mensagem de confirmação de pagamento (recorrência)

**Bug reportado pelo usuário**: mensagens de "Renovação confirmada" chegavam **em duplicidade** ao cliente.

**Root cause encontrado em `routers/payments.py::_process_payment_confirmation`:**

1. **Confirmação sem `transaction_nsu` seguida do webhook oficial** (fluxo mais comum):
   - Cliente volta do InfinitePay → `/pay/{id}?ok=1` → frontend chama `/check-status`.
   - A estratégia 1 (`check_payment`) confirma o pagamento — mas a API `/payment_check` da InfinitePay **NÃO retorna `transaction_nsu`**.
   - O pagamento vira `status='paid'` com `transaction_nsu=""` e a mensagem é enviada. ✅
   - Minutos depois o **webhook oficial** chega COM `transaction_nsu=XXXX`.
   - A lógica antiga interpretava isso como "nova captura no mesmo link" (linha 595: `if transaction_nsu != (payment.get("transaction_nsu") or "")` → `"XXXX" != ""` → TRUE), clonava o pagamento e **reprocessava tudo**: `painel.renew_user` + envio de `renewal_success`. 🐛
   - **Impacto**: cliente recebia 2 mensagens + ganhava 1 mês extra sem pagar.

2. **Race condition** entre webhook + poller processando o mesmo pagamento em paralelo — sem guard atômico, ambos podiam flippar `pending → paid` e disparar `renewal_success`.

**Correções aplicadas:**

- **Clone só quando o `transaction_nsu` já armazenado ≠ do novo E o armazenado NÃO é vazio.** Se o pagamento estava marcado pago mas sem `transaction_nsu`, o webhook agora apenas **backfilla** o campo silenciosamente e retorna `already_processed` — sem re-notificar nem re-renovar.
- **Guard de race no UPDATE `pending → paid`**: adicionado `WHERE status = 'pending'` no UPDATE. Se `rowcount == 0`, significa que outro caller já flipou — retorna `already_processed` (idempotent_by=`race_guard`) sem re-enviar mensagem.

**Testes de regressão** (`tests/test_dedup_confirmation.py`, 3 casos):
1. `test_pay_return_then_webhook_does_not_reclone` — cenário exato do bug: check-status confirma sem txn_nsu, webhook depois com txn_nsu. Verifica que renewal + notificação disparam **exatamente 1x** e nenhum clone é criado.
2. `test_second_webhook_with_new_txn_still_clones` — sanity: cliente que legitimamente paga 2x no mesmo link (2 txn_nsu distintos) ainda dispara 2 renovações.
3. `test_concurrent_pending_confirmation_only_notifies_once` — `asyncio.gather` de 2 chamadas simultâneas, valida que apenas 1 renovação dispara.

Todos os 3 novos testes + 54 testes de regressão passando.



## [FEATURE 2026-02-27] Sistema de Cupons de Desconto (P0 — CONCLUÍDO)

Nova funcionalidade para incentivar renovações com códigos de desconto rastreáveis.

**Regras (confirmadas com produto):**
- Desconto máximo: **50%** (valores acima são limitados automaticamente).
- Cupom só "conta como usado" quando o pagamento é **CONFIRMADO** pela InfinitePay.
- Cada cliente pode usar **1 cupom a cada 28 dias** (regra por cliente, independente do código).
- Cliente identificado pelo `customer_id` da URL `/pay/{id}` (que é o `painel_username`).
- Cupom tem apenas estado ativo/inativo (sem data de expiração).
- Se o cliente já tem desconto automático de 7 dias ativo, o **maior** desconto vence — se o cupom perder, ele é ignorado (não conta o uso).

**Backend:**
- `services/coupon.py` — validate_coupon, record_usage, normalize_code, clamp_percent (50%), has_recent_usage (28d).
- `routers/coupons.py` — CRUD + `POST /api/coupons/validate` (público, sem auth).
- `routers/payments.py` — `create_payment` aceita `coupon_code`; usage registrado em `_process_payment_confirmation` (idempotente).
- Tabelas `coupons` e `coupon_usages` + colunas `coupon_code`/`coupon_id` em `payments`.

**Frontend:**
- `pages/Coupons.jsx` — página CRUD (cards, editar, remover, ver usos).
- `pages/PublicPay.jsx` — input "Cupom" + botão "Aplicar" no checkout, preço original riscado + preço com desconto.
- `pages/Payments.jsx` — badge do cupom aplicado no histórico admin.
- `components/Sidebar.jsx` — link "Cupons" (nav-coupons).

**Testes (100% passing):**
- 10 unit tests em `tests/test_coupons.py` (validação, cooldown, clamp).
- 13 HTTP integration tests em `tests/test_coupons_integration.py` (adicionado pelo testing agent).
- 45 testes de regressão continuam verdes.


## Implemented (2026-02)

- **[FIX 2026-02-22 P0]** **Mobile responsivo completo** (validado 100% pelo testing agent em viewport 375×812):
  - **Sidebar hamburger**: em mobile (<768px) a sidebar vira drawer overlay. Top-bar preta fixa com ícone hamburger (`btn-open-menu`). Drawer abre da esquerda, X no cabeçalho fecha, clicar fora do drawer fecha, navegar fecha automaticamente. Desktop mantém sidebar fixa de 256px.
  - **Layout header responsivo**: title/subtitle empilha em coluna no mobile, buttons usam `flex-wrap` para não sair da tela. `pt-14 md:pt-0` evita conteúdo atrás do top-bar mobile.
  - **ColumnPicker sempre visível**: movido para PRIMEIRA posição no `actions` de Customers.jsx (antes ficava soterrado). Payments.jsx passa `actions={<ColumnPicker />}` direto.
  - **Tabelas com scroll horizontal**: `overflow-x-auto` + `min-w-[640px]` — sem quebrar layout em mobile.



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
