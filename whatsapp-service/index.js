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
const os = require('os');
// Session dir OUTSIDE git repo — avoids EACCES and git pull conflicts.
// Default: ~/.whatsflow/wwebjs_auth. Override via WA_SESSION_DIR env.
const SESSION_DIR = process.env.WA_SESSION_DIR || path.join(os.homedir(), '.whatsflow', 'wwebjs_auth');
console.log('[WA] Session dir:', SESSION_DIR);

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
client.on('message_create', async (msg) => {
  try {
    if (msg.from === 'status@broadcast' || msg.to === 'status@broadcast') return;
    if (msg.from?.endsWith('@g.us') || msg.to?.endsWith('@g.us')) return;
    const body = msg.body || '';
    if (!body.trim()) return;

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
    res.json({ success: true, id: result.id?._serialized, chat_id: chatId });
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

process.on('SIGTERM', async () => {
  try { await client.destroy(); } catch {}
  process.exit(0);
});
