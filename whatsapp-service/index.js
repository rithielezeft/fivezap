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
    // Raw jid could be <phone>@c.us or <lid>@lid (new WhatsApp Web protocol).
    const rawJid = fromMe ? msg.to : msg.from;

    // Resolve to actual phone number. For @c.us the number is the digits before @.
    // For @lid we need to look up the contact and get its .number property.
    let phone = null;
    let phoneSource = 'unknown';
    try {
      if (rawJid?.endsWith('@lid')) {
        const contact = await client.getContactById(rawJid);
        phone = contact?.number || null;
        phoneSource = phone ? 'lid-resolved' : 'lid-unresolved';
        // Fallback 1: contact.pushname may contain phone in some cases
        // Fallback 2: check msg.rawData for pn (phone number) field
        if (!phone && msg._data?.pn) {
          phone = String(msg._data.pn).replace(/\D/g, '');
          phoneSource = 'msg._data.pn';
        }
        if (!phone && msg.author?.includes('@c.us')) {
          phone = msg.author.split('@')[0];
          phoneSource = 'msg.author';
        }
        if (!phone) {
          console.warn('[WA] Could NOT resolve LID → phone. Raw:', rawJid, 'contact:', contact?.id, 'msg._data.pn:', msg._data?.pn, 'author:', msg.author);
        }
      } else if (rawJid?.includes('@')) {
        phone = rawJid.split('@')[0];
        phoneSource = 'c.us';
      } else {
        phone = rawJid;
        phoneSource = 'raw';
      }
    } catch (e) {
      console.warn('[WA] Contact lookup failed:', rawJid, e.message);
      phone = null;
      phoneSource = 'error';
    }

    if (!phone || !/^\d{8,15}$/.test(String(phone))) {
      console.warn('[WA] ⚠️  DROPPING message: invalid phone', { rawJid, phone, phoneSource, body: body.slice(0, 60) });
      return;
    }

    console.log('[WA] message_create', { from_me: fromMe, phone, phoneSource, body: body.slice(0, 80) });

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
    // Strip everything but digits (no +, no @c.us — getNumberId handles that)
    const digits = String(phone).replace(/\D/g, '');
    if (!digits) return res.status(400).json({ error: 'invalid phone (no digits)' });

    // Resolve to a proper WhatsApp ID (handles LID conversion internally in 1.34.7+)
    let chatId;
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
      // Fallback to old format if getNumberId fails outright
      console.warn('[WA] getNumberId failed, falling back to @c.us:', lidErr.message);
      chatId = `${digits}@c.us`;
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
