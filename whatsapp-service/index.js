/**
 * WhatsFlow — WhatsApp Service (whatsapp-web.js)
 * Exposes HTTP API at :3001 for the FastAPI backend.
 */
const express = require('express');
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const axios = require('axios');

const PORT = process.env.PORT || 3001;
const BACKEND_WEBHOOK_URL = process.env.BACKEND_WEBHOOK_URL || 'http://localhost:8001/api/whatsapp/incoming';

let currentQR = null;
let ready = false;
let state = 'starting';
let lastError = null;

const path = require('path');
const fs = require('fs');
const os = require('os');
// Session dir OUTSIDE git repo — avoids EACCES and git pull conflicts.
// Default: ~/.whatsflow/wwebjs_auth. Override via WA_SESSION_DIR env.
const SESSION_DIR = process.env.WA_SESSION_DIR || path.join(os.homedir(), '.whatsflow', 'wwebjs_auth');
console.log('[WA] Session dir:', SESSION_DIR);

// ---- Clean up stale Chrome/Puppeteer lock files ----
// When systemd kills the service without a graceful shutdown, Chrome leaves
// behind a `SingletonLock` (and friends) inside the userDataDir. The next
// launch then dies with:
//   "The browser is already running for .../session-whatsflow.
//    Use a different `userDataDir` or stop the running browser first."
// We proactively remove these lock files at startup so restarts always work.
function clearChromeStaleLocks(root) {
  if (!fs.existsSync(root)) return;
  const LOCK_NAMES = ['SingletonLock', 'SingletonCookie', 'SingletonSocket', 'lockfile'];
  function walk(dir, depth) {
    if (depth > 5) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
    catch { return; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      try {
        if (e.isSymbolicLink() && LOCK_NAMES.includes(e.name)) {
          fs.unlinkSync(full);
          console.log('[WA] Removed stale Chrome lock:', full);
        } else if (e.isFile() && LOCK_NAMES.includes(e.name)) {
          fs.unlinkSync(full);
          console.log('[WA] Removed stale Chrome lock:', full);
        } else if (e.isDirectory()) {
          walk(full, depth + 1);
        }
      } catch (err) {
        console.warn('[WA] Could not remove', full, err.message);
      }
    }
  }
  walk(root, 0);
}

clearChromeStaleLocks(SESSION_DIR);

// Also kill any orphan chrome/chromium processes bound to our session dir.
// This handles the case where a previous puppeteer instance crashed but its
// Chrome subprocess is still alive holding the profile.
try {
  const { execSync } = require('child_process');
  const pgrepOut = execSync(
    `pgrep -a -f "${SESSION_DIR}" 2>/dev/null || true`,
    { encoding: 'utf8' }
  );
  const pids = pgrepOut
    .split('\n')
    .filter(Boolean)
    .filter((line) => /(chrome|chromium|node)/i.test(line))
    .filter((line) => !line.includes(String(process.pid)))
    .map((line) => parseInt(line.split(' ')[0], 10))
    .filter((pid) => !isNaN(pid) && pid !== process.pid);
  for (const pid of pids) {
    try {
      process.kill(pid, 'SIGKILL');
      console.log('[WA] Killed orphan Chrome/Chromium PID:', pid);
    } catch (e) {
      console.warn('[WA] Failed to kill PID', pid, e.message);
    }
  }
} catch (e) {
  console.warn('[WA] Orphan process cleanup failed (non-fatal):', e.message);
}

// Chromium/Chrome path detection — Raspberry Pi (ARM) usually ships
// `chromium-browser` or `chromium` via apt, NOT `google-chrome`. Falling
// back through common paths avoids the "starting" hang caused by Puppeteer
// failing to spawn the browser (TargetCloseError).
function _resolveChromiumPath() {
  const explicit = process.env.CHROMIUM_PATH;
  if (explicit) return explicit;
  const fs = require('fs');
  // Prefer REAL binaries first — shell wrappers cause TargetCloseError because
  // Puppeteer's PID handle refers to the wrapper, which exits after spawning
  // the real browser, breaking the DevTools protocol handshake.
  const candidates = [
    // Real binaries (Debian/RPi OS install these under /usr/lib/*)
    '/usr/lib/chromium/chrome',
    '/usr/lib/chromium/chromium',
    '/usr/lib/chromium-browser/chromium-browser',
    // Common apt-installed paths (may be real OR wrapper — checked below)
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/snap/bin/chromium',
  ];

  // Helper: reject POSIX shell scripts. Puppeteer needs the real ELF binary.
  function _isRealBinary(p) {
    try {
      const buf = Buffer.alloc(4);
      const fd = fs.openSync(p, 'r');
      fs.readSync(fd, buf, 0, 4, 0);
      fs.closeSync(fd);
      // ELF magic: 0x7F 'E' 'L' 'F'
      return buf[0] === 0x7f && buf[1] === 0x45 && buf[2] === 0x4c && buf[3] === 0x46;
    } catch (e) { return false; }
  }

  for (const p of candidates) {
    try {
      if (!fs.existsSync(p)) continue;
      if (!_isRealBinary(p)) {
        console.warn('[WA] Skipping', p, '— it is a shell wrapper, not the real Chromium binary');
        continue;
      }
      console.log('[WA] Using Chromium at', p);
      return p;
    } catch (e) {}
  }

  console.error('════════════════════════════════════════════════════════');
  console.error('[WA] ❌ NENHUM CHROMIUM (BINÁRIO REAL) ENCONTRADO!');
  console.error('[WA] Encontrei apenas wrappers shell — Puppeteer não funciona com wrappers.');
  console.error('[WA] Instale com:  sudo apt install -y chromium');
  console.error('[WA] Ou aponte manualmente: export CHROMIUM_PATH=/caminho/do/binario/real');
  console.error('════════════════════════════════════════════════════════');
  return undefined;
}

const client = new Client({
  authStrategy: new LocalAuth({ clientId: 'whatsflow', dataPath: SESSION_DIR }),
  // Pin the WA Web HTML to a known-good version — WhatsApp updates web.whatsapp.com
  // frequently and it breaks whatsapp-web.js's inject step (Client.inject) with
  // "TargetCloseError: Target closed". Pinning to a specific HTML from the
  // community-maintained wa-version repo fixes this until the library updates.
  webVersionCache: {
    type: 'remote',
    remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.3000.1045805239-alpha.html',
  },
  puppeteer: {
    // MUST be 'new' — Chromium 132+ removed the old headless mode. Passing
    // `headless: true` becomes `--headless=old` on some puppeteer versions
    // and Chromium immediately exits with TargetCloseError.
    headless: 'new',
    executablePath: _resolveChromiumPath(),
    // Bump the protocol timeout so Page.navigate doesn't fail on slow
    // Raspberry Pi hardware. Default is 30s — WA web can take 60+ on ARM.
    protocolTimeout: 180000,
    args: [
      // Explicit new headless mode — belt & suspenders in case an old
      // puppeteer builds the old --headless flag from `headless: true`.
      '--headless=new',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-extensions',
      '--no-first-run',
      // Raspberry Pi friendly flags — cut GPU + software rasterizer paths
      // that spawn extra processes and increase the chance of Target closed.
      '--disable-gpu',
      '--disable-software-rasterizer',
      '--disable-features=Translate,BackForwardCache,MediaRouter,DialMediaRouteProvider',
      '--no-zygote',
      '--mute-audio',
    ],
  },
});

// Reconnect state machine — exponential backoff up to 5min, resets after
// a successful `ready` event. Also runs a periodic watchdog every 30s that
// force-reconnects when the client has been in a non-connected state for
// longer than 3 minutes.
let _reconnectAttempts = 0;
let _lastReadyAt = null;
let _lastStateChangeAt = Date.now();
let _stateForWatchdog = state;

function _scheduleReconnect(sourceLabel) {
  _reconnectAttempts += 1;
  // Backoff: 5s, 10s, 30s, 1m, 2m, 5m (cap)
  const schedule = [5000, 10000, 30000, 60000, 120000, 300000];
  const delay = schedule[Math.min(_reconnectAttempts - 1, schedule.length - 1)];
  console.warn(`[WA] Reconnect attempt #${_reconnectAttempts} from ${sourceLabel} in ${delay}ms`);
  setTimeout(() => {
    try {
      // A hard destroy → initialize is more reliable than initialize() alone
      // when the underlying puppeteer session is stuck.
      client.destroy()
        .catch((e) => console.warn('[WA] destroy failed (non-fatal):', e.message))
        .finally(() => {
          client.initialize().catch((e) => {
            console.error('[WA] initialize() during reconnect failed:', e.message);
            _scheduleReconnect('post-initialize-error');
          });
        });
    } catch (e) {
      console.error('[WA] Reconnect crashed:', e.message);
    }
  }, delay);
}

function _markStateChange(newState) {
  if (newState !== _stateForWatchdog) {
    _stateForWatchdog = newState;
    _lastStateChangeAt = Date.now();
  }
}

// Watchdog: every 30s, if we've been in a non-connected state for more than
// 3 minutes AND no reconnect is already scheduled, force one. This catches
// the "silent zombie" case where events stop firing but no `disconnected`
// event was emitted (Chrome crash, network drop, etc.).
setInterval(() => {
  _markStateChange(state);
  if (state === 'connected') return;
  const stuckMs = Date.now() - _lastStateChangeAt;
  if (stuckMs > 3 * 60 * 1000) {
    console.warn(`[WA] Watchdog: stuck in "${state}" for ${Math.floor(stuckMs / 1000)}s — forcing reconnect`);
    _lastStateChangeAt = Date.now();  // reset so we don't spam every 30s
    _scheduleReconnect('watchdog');
  }
}, 30000);

client.on('qr', async (qr) => {
  state = 'awaiting_qr';
  ready = false;
  try {
    currentQR = await qrcode.toDataURL(qr);
    console.log('[WA] QR code updated');
  } catch (e) {
    console.error('[WA] QR encode error', e);
  }
});

client.on('ready', () => {
  console.log('[WA] Client ready');
  ready = true;
  state = 'connected';
  currentQR = null;
  lastError = null;
  _reconnectAttempts = 0;
  _lastReadyAt = Date.now();
  _lastStateChangeAt = Date.now();
});

client.on('authenticated', () => {
  console.log('[WA] Authenticated');
  state = 'authenticated';
});

client.on('auth_failure', (msg) => {
  console.error('[WA] Auth failure', msg);
  state = 'auth_failure';
  lastError = String(msg);
  ready = false;
});

client.on('disconnected', (reason) => {
  console.warn('[WA] Disconnected:', reason);
  ready = false;
  state = 'disconnected';
  lastError = String(reason);
  _scheduleReconnect('disconnected-event');
});

// Use ONLY `message_create` — it fires for BOTH incoming (client) and
// outgoing (admin) messages, WITHOUT requiring the chat to be opened first.
// Deduplication: `message_create` sometimes fires more than once for the same
// message id (especially with LID chats on multi-device). We track recently
// processed message ids in an in-memory Map with a 60s TTL.
const _seenMessages = new Map(); // msgId -> timestamp
function _seenRecently(msgId) {
  const now = Date.now();
  // Purge entries older than 60s
  for (const [k, t] of _seenMessages) {
    if (now - t > 60_000) _seenMessages.delete(k);
  }
  if (_seenMessages.has(msgId)) return true;
  _seenMessages.set(msgId, now);
  return false;
}

client.on('message_create', async (msg) => {
  try {
    if (msg.from === 'status@broadcast' || msg.to === 'status@broadcast') return;
    if (msg.from?.endsWith('@g.us') || msg.to?.endsWith('@g.us')) return;
    const body = msg.body || '';
    if (!body.trim()) return;

    // Dedup by message id — prevents double-processing when message_create fires 2x
    const msgId = msg.id?._serialized || msg.id?.id;
    if (msgId && _seenRecently(msgId)) {
      console.log('[WA] duplicate message_create suppressed', msgId);
      return;
    }

    const fromMe = !!msg.fromMe;
    // Raw jid — this is a valid WhatsApp identifier (either <phone>@c.us OR <lid>@lid).
    // WhatsApp's new privacy feature: some users have @lid where the real phone is
    // hidden. Instead of trying to resolve LID→phone (which often returns null),
    // we FORWARD THE FULL JID to the backend and use it verbatim to send back.
    const rawJid = fromMe ? msg.to : msg.from;
    if (!rawJid) return;

    // Extract a usable "phone identifier" — could be digits (@c.us) OR digits+@lid marker
    // Backend uses this as the unique key AND as the chat target for sending back.
    let phone;
    if (rawJid.endsWith('@lid')) {
      // Preserve @lid so backend knows to send back using LID chat
      phone = rawJid;
    } else if (rawJid.endsWith('@c.us')) {
      phone = rawJid.split('@')[0];
    } else {
      phone = rawJid;
    }

    // Try to extract a display name for the customer + real phone number.
    // WhatsApp's LID privacy protocol hides the phone in the JID, but the
    // Contact object frequently still exposes the real number via
    // `contact.number` (E.164 without +) when privacy allows. We ALSO try
    // `client.getContactLidAndPhone([lid])` — the documented batch API that
    // sometimes maps LID→phone even when contact.number is null.
    // We EXPLICITLY do NOT fall back to `contact.id.user` for LID contacts:
    // for @lid, id.user IS the LID digits (15-18+ digits) which look like a
    // phone but are NOT. Sending them to painel.fun as reseller_notes would
    // register garbage numbers like +191134936608840.
    let displayName = null;
    let realPhone = null;

    const _isPlausiblePhone = (s) => {
      // E.164 allows up to 15 digits. Real WhatsApp phone numbers are
      // typically 10-13 digits (BR: 12-13). LID identifiers are usually
      // 15-18+ digits. Cap conservatively at 14 to avoid LID false-positives.
      const d = String(s || '').replace(/\D/g, '');
      return d.length >= 8 && d.length <= 14;
    };

    try {
      displayName = msg._data?.notifyName || msg.notifyName || null;

      // senderPn is present on some LID/community messages and IS the
      // real phone number when exposed by WhatsApp
      const senderPn = msg._data?.senderPn || null;
      if (senderPn && _isPlausiblePhone(senderPn)) {
        realPhone = String(senderPn).replace(/\D/g, '');
      }

      if (!displayName || !realPhone) {
        const contact = await msg.getContact();
        if (!displayName) {
          displayName = contact?.pushname || contact?.name || contact?.shortName || null;
        }
        // ONLY use contact.number (the real phone digits). Skip
        // contact.id.user because for LID it's the LID itself, not a phone.
        if (!realPhone && contact?.number && _isPlausiblePhone(contact.number)) {
          realPhone = String(contact.number).replace(/\D/g, '');
        }
        // Last resort for LID chats: try the batch mapping API.
        // client.getContactLidAndPhone accepts an array of ids and returns
        // objects with .pn (phone number) filled when WhatsApp exposes it.
        if (!realPhone && rawJid.endsWith('@lid')) {
          try {
            if (typeof client.getContactLidAndPhone === 'function') {
              const mapping = await client.getContactLidAndPhone([rawJid]);
              const entry = Array.isArray(mapping) ? mapping[0] : mapping;
              const pn = entry?.pn || entry?.phone || entry?.number || null;
              if (pn && _isPlausiblePhone(pn)) {
                realPhone = String(pn).replace(/\D/g, '');
                console.log('[WA] LID resolved via getContactLidAndPhone:',
                  rawJid, '→', realPhone);
              }
            }
          } catch (lidErr) {
            // Non-fatal: some builds don't have this method yet.
          }
        }
      }
    } catch (e) {
      // Non-fatal
    }

    console.log('[WA] message_create', {
      from_me: fromMe, phone, real_phone: realPhone,
      name: displayName, body: body.slice(0, 80),
    });

    await axios.post(BACKEND_WEBHOOK_URL, {
      phone,
      message: body,
      from_me: fromMe,
      name: displayName,
      real_phone: realPhone,
    }, { timeout: 8000 });
  } catch (e) {
    console.error('[WA] Webhook error', e.message);
  }
});

// Add delay before initialize to avoid "Requesting main frame too early" race condition
setTimeout(() => {
  client.initialize().catch((e) => {
    console.error('[WA] Initialize error', e);
    state = 'error';
    lastError = String(e);
    // ProtocolError, timeout, Chrome crash on startup → escalate to the
    // reconnect state machine instead of dying silently.
    _scheduleReconnect('initial-initialize-error');
  });
}, 2000);

// -------- HTTP API --------
const app = express();
app.use(express.json());

// Reconnect state — how many retry attempts, when last ready was, etc.
app.get('/reconnect-state', (req, res) => {
  res.json({
    attempts: _reconnectAttempts,
    last_ready_at: _lastReadyAt,
    last_state_change_at: _lastStateChangeAt,
    current_state: state,
  });
});

app.get('/status', (req, res) => {
  res.json({ ready, state, error: lastError, has_qr: !!currentQR });
});

app.get('/qr', (req, res) => {
  res.json({ qr: currentQR, ready, state });
});

app.post('/send', async (req, res) => {
  const { phone, message, image_url } = req.body || {};
  if (!phone) return res.status(400).json({ error: 'phone required' });
  if (!ready) return res.status(503).json({ error: 'whatsapp not ready', state });
  try {
    // Accept 3 input formats:
    //   1. Full JID with @lid  → use as-is (LID chat, new privacy protocol)
    //   2. Full JID with @c.us → use as-is
    //   3. Plain digits         → resolve via getNumberId (registered check)
    const input = String(phone).trim();
    let chatId;

    if (input.endsWith('@lid') || input.endsWith('@c.us') || input.endsWith('@g.us') || input.endsWith('@newsletter') || input.endsWith('@broadcast')) {
      chatId = input;
    } else {
      const digits = input.replace(/\D/g, '');
      if (!digits) return res.status(400).json({ error: 'invalid phone (no digits)' });
      try {
        const numberId = await client.getNumberId(digits);
        if (!numberId) {
          console.warn('[WA] Number not registered on WhatsApp:', digits);
          return res.status(404).json({
            error: 'Este número não está no WhatsApp',
            phone: digits,
          });
        }
        chatId = numberId._serialized;
      } catch (lidErr) {
        console.warn('[WA] getNumberId failed, falling back to @c.us:', lidErr.message);
        chatId = `${digits}@c.us`;
      }
    }

    // Optional typing indicator: show "digitando..." for N ms before sending
    // the message. Simulates a human writing, reduces WA anti-spam heuristics,
    // and makes notifications feel more personal.
    const typingMs = Math.max(0, Math.min(15000, parseInt(req.body.typing_ms) || 0));
    if (typingMs > 0) {
      try {
        const chat = await client.getChatById(chatId);
        await chat.sendStateTyping();
        await new Promise((resolve) => setTimeout(resolve, typingMs));
        // Do NOT clear state — sendMessage below will replace it naturally.
      } catch (typingErr) {
        console.warn('[WA] sendStateTyping failed (non-fatal):', typingErr.message);
      }
    }

    let result;
    if (image_url) {
      const { MessageMedia } = require('whatsapp-web.js');
      let media;
      if (image_url.startsWith('data:')) {
        const [meta, b64] = image_url.split(',');
        const mime = meta.split(':')[1].split(';')[0];
        media = new MessageMedia(mime, b64, 'image');
      } else {
        media = await MessageMedia.fromUrl(image_url, { unsafeMime: true });
      }
      result = await client.sendMessage(chatId, media, { caption: message || '' });
    } else {
      if (!message) return res.status(400).json({ error: 'message or image_url required' });
      result = await client.sendMessage(chatId, message);
    }
    // In some LID chats, `sendMessage` returns undefined even on success.
    // Treat undefined/null as "sent OK" — the message was delivered.
    const messageId = result?.id?._serialized || result?.id?.id || null;
    res.json({ success: true, id: messageId, chat_id: chatId });
  } catch (e) {
    console.error('[WA] Send error', e);
    res.status(500).json({ error: e.message });
  }
});

app.get('/chats', async (req, res) => {
  // List chats filtered by type — "group" or "newsletter" (aka Channel).
  // Used by /api/whatsapp/groups + /api/whatsapp/channels on the backend
  // for the "send to group/channel" feature.
  if (!ready) return res.status(503).json({ error: 'whatsapp not ready', state });
  const type = String(req.query.type || 'group').toLowerCase();
  try {
    const chats = await client.getChats();
    const filtered = chats
      .filter((c) => {
        if (type === 'group') return c.isGroup === true;
        if (type === 'newsletter' || type === 'channel') {
          // Newsletters are the internal name for Channels. Detect via id
          // suffix (`@newsletter`) and/or the `isNewsletter` flag.
          const id = c.id?._serialized || '';
          return c.isNewsletter === true || id.endsWith('@newsletter');
        }
        return false;
      })
      .map((c) => ({
        id: c.id?._serialized || String(c.id),
        name: c.name || c.formattedTitle || '(sem nome)',
        is_group: c.isGroup === true,
        is_newsletter: c.isNewsletter === true,
        participants_count: c.groupMetadata?.participants?.length || 0,
        unread_count: c.unreadCount || 0,
      }));
    res.json({ chats: filtered, count: filtered.length });
  } catch (e) {
    console.error('[WA] /chats error', e);
    res.status(500).json({ error: e.message });
  }
});


app.post('/logout', async (req, res) => {  try {
    await client.logout();
    ready = false;
    state = 'disconnected';
    currentQR = null;
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`[WA] Service listening on :${PORT}`);
});

async function gracefulShutdown(signal) {
  console.log(`[WA] Received ${signal}, shutting down gracefully...`);
  try {
    await client.destroy();
    console.log('[WA] Client destroyed');
  } catch (e) {
    console.warn('[WA] client.destroy() error:', e.message);
  }
  // Give Chrome a moment to release the lock, then remove any leftover.
  setTimeout(() => {
    try { clearChromeStaleLocks(SESSION_DIR); } catch {}
    process.exit(0);
  }, 800);
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));
