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

const client = new Client({
  authStrategy: new LocalAuth({ clientId: 'whatsflow', dataPath: SESSION_DIR }),
  puppeteer: {
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || '/usr/bin/google-chrome',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-extensions',
      '--no-first-run',
    ],
  },
});

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
  // Attempt to re-initialize
  setTimeout(() => client.initialize().catch(console.error), 5000);
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

    // Try to extract a display name for the customer
    let displayName = null;
    try {
      displayName = msg._data?.notifyName || msg.notifyName || null;
      if (!displayName) {
        const contact = await msg.getContact();
        displayName = contact?.pushname || contact?.name || contact?.shortName || null;
      }
    } catch (e) {
      // Non-fatal
    }

    console.log('[WA] message_create', {
      from_me: fromMe, phone, name: displayName, body: body.slice(0, 80),
    });

    await axios.post(BACKEND_WEBHOOK_URL, {
      phone,
      message: body,
      from_me: fromMe,
      name: displayName,
    }, { timeout: 8000 });

    await axios.post(BACKEND_WEBHOOK_URL, {
      phone,
      message: body,
      from_me: fromMe,
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
  });
}, 2000);

// -------- HTTP API --------
const app = express();
app.use(express.json());

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

    if (input.endsWith('@lid') || input.endsWith('@c.us') || input.endsWith('@g.us')) {
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

app.post('/logout', async (req, res) => {
  try {
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
