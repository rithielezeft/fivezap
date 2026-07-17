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

const client = new Client({
  authStrategy: new LocalAuth({ clientId: 'whatsflow', dataPath: '/app/whatsapp-service/.wwebjs_auth' }),
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

client.on('message', async (msg) => {
  try {
    console.log('[WA] Incoming', msg.from, '->', msg.body?.slice(0, 80));
    await axios.post(BACKEND_WEBHOOK_URL, {
      phone: msg.from,
      message: msg.body || '',
      from_me: false,
    }, { timeout: 8000 });
  } catch (e) {
    console.error('[WA] Webhook error', e.message);
  }
});

client.on('message_create', async (msg) => {
  // Also forward messages the user (admin) sends from their phone so we can trigger commands as admin
  if (!msg.fromMe) return;
  try {
    await axios.post(BACKEND_WEBHOOK_URL, {
      phone: msg.to,
      message: msg.body || '',
      from_me: true,
    }, { timeout: 8000 });
  } catch (e) {
    console.error('[WA] Webhook error (outgoing)', e.message);
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
    const digits = String(phone).replace(/\D/g, '');
    const chatId = digits.includes('@') ? digits : `${digits}@c.us`;

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
    res.json({ success: true, id: result.id?._serialized });
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
