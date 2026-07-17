# 🍓 WhatsFlow — Guia de Deploy na Raspberry Pi

Este guia mostra como colocar o WhatsFlow para rodar 24/7 na sua Raspberry Pi
(recomendado: **Raspberry Pi 4 com 4GB+ RAM** e Raspberry Pi OS 64-bit).

> ⚠️ **Por que rodar em casa (residencial)?** O `painel.fun` está protegido
> pelo Cloudflare, que **bloqueia IPs de datacenter/nuvem** para o endpoint de
> login. Sua conexão residencial (Raspberry Pi na sua casa) passa sem problemas.

---

## 1) Requisitos do sistema

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nodejs npm chromium-browser \
    libnss3 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxrandr2 libxdamage1 \
    libxfixes3 libxi6 libgbm1 libpangocairo-1.0-0 libasound2
```

Instale yarn:
```bash
sudo npm install -g yarn
```

Verifique versões (recomendado):
- Python 3.10+
- Node.js 18+ (`node -v`)
- Chromium 100+

---

## 2) Clone e prepare o código

```bash
cd /home/pi
git clone <seu-repo> whatsflow
cd whatsflow
```

### Backend (FastAPI + SQLite)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Crie o `.env`:
```bash
cat > .env <<EOF
# Backend
JWT_SECRET="$(openssl rand -hex 64)"
ADMIN_PASSWORD="Rithi0518@"

# NÃO ALTERE — legado (não usado)
MONGO_URL="mongodb://localhost:27017"
DB_NAME="whatsflow"
CORS_ORIGINS="*"

# Onde salvar o SQLite (opcional — padrão: backend/whatsflow.db)
# SQLITE_PATH="/home/pi/whatsflow/backend/whatsflow.db"
EOF
```

### WhatsApp Service (Node.js)

```bash
cd ../whatsapp-service
yarn install
```

O `whatsapp-web.js` usará automaticamente o `google-chrome` ou `chromium-browser`.
Se preferir, defina em `.env`:
```bash
export CHROMIUM_PATH="/usr/bin/chromium-browser"
```

### Frontend (React)

```bash
cd ../frontend
yarn install

# Configure a URL pública (mesmo IP local ou seu domínio + reverse proxy)
cat > .env <<EOF
REACT_APP_BACKEND_URL="https://whatsflow.zeferius.com"
EOF

# Build para produção
yarn build
```

---

## 3) Rodar como serviço com systemd (24/7)

### Backend (porta 8001)

```bash
sudo tee /etc/systemd/system/whatsflow-backend.service > /dev/null <<'EOF'
[Unit]
Description=WhatsFlow Backend (FastAPI)
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/whatsflow/backend
Environment="PATH=/home/pi/whatsflow/backend/.venv/bin"
ExecStart=/home/pi/whatsflow/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

> **Obs:** Como o backend já **spawna sozinho** o serviço Node WhatsApp
> (via subprocess no `lifespan`), só precisa deste service. Se quiser
> desabilitar o auto-spawn e rodar em separado, use o service abaixo.

### WhatsApp Service em separado (opcional)

Se preferir rodar em paralelo (mais fácil de debugar / logs separados):

Em `backend/server.py` desabilite o `_start_whatsapp_service()` na função lifespan (ou apenas ignore — nada quebra se ambos rodarem no mesmo comando via subprocess).

```bash
sudo tee /etc/systemd/system/whatsflow-wa.service > /dev/null <<'EOF'
[Unit]
Description=WhatsFlow WhatsApp Service (whatsapp-web.js)
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/whatsflow/whatsapp-service
Environment="PORT=3001"
Environment="BACKEND_WEBHOOK_URL=http://localhost:8001/api/whatsapp/incoming"
Environment="CHROMIUM_PATH=/usr/bin/chromium-browser"
ExecStart=/usr/bin/node index.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### Frontend (nginx serve o build)

```bash
sudo apt install -y nginx
sudo tee /etc/nginx/sites-available/whatsflow > /dev/null <<'EOF'
server {
    listen 80;
    server_name whatsflow.zeferius.com;

    # Frontend estático
    root /home/pi/whatsflow/frontend/build;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    # API → backend :8001
    location /api/ {
        proxy_pass http://localhost:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        client_max_body_size 10M;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/whatsflow /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### HTTPS grátis com Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d whatsflow.zeferius.com
```

### Ativar todos os serviços

```bash
sudo systemctl daemon-reload
sudo systemctl enable whatsflow-backend whatsflow-wa nginx
sudo systemctl start whatsflow-backend whatsflow-wa

# Verificar
sudo systemctl status whatsflow-backend
sudo journalctl -u whatsflow-backend -f
```

---

## 4) Configuração inicial

1. **Acesse** `https://whatsflow.zeferius.com/login` → senha `Rithi0518@`
2. **Configurações** → preencha:
   - `InfinitePay handle` (InfiniteTag da sua conta)
   - Preços dos planos (em R$: `35,00`, `90,00`, etc.)
   - Confira `notification_days: 7,3,1,0,-1,-3,-7`
3. **WhatsApp** → escaneie o QR (sessão fica salva em `.wwebjs_auth/`)
4. **Notificações** → personalize cada template, faça upload de imagens
5. **Comandos** → cadastre `/teste p2p`, `/teste iptv MAC`, etc.
6. **Clientes** → clique "Atualizar do painel" (leva ~1 min por causa do 2Captcha)

---

## 5) Backup do banco de dados

O SQLite fica em `/home/pi/whatsflow/backend/whatsflow.db`. Faça backup diário:

```bash
sudo tee /etc/cron.daily/whatsflow-backup > /dev/null <<'EOF'
#!/bin/bash
mkdir -p /home/pi/backups
cp /home/pi/whatsflow/backend/whatsflow.db /home/pi/backups/whatsflow-$(date +%Y%m%d).db
find /home/pi/backups -name "whatsflow-*.db" -mtime +30 -delete
EOF
sudo chmod +x /etc/cron.daily/whatsflow-backup
```

---

## 6) Atualização (pull + rebuild)

```bash
cd /home/pi/whatsflow
git pull
cd backend && source .venv/bin/activate && pip install -r requirements.txt
cd ../whatsapp-service && yarn install
cd ../frontend && yarn install && yarn build
sudo systemctl restart whatsflow-backend whatsflow-wa nginx
```

---

## 7) Portas usadas

| Serviço          | Porta | Descrição                          |
|------------------|-------|--------------------------------------|
| Nginx            | 80/443| Site público (SSL via Certbot)      |
| Backend FastAPI  | 8001  | API interna (só localhost)          |
| WhatsApp Node    | 3001  | API interna (só localhost)          |
| Frontend build   | -     | Servido estaticamente pelo Nginx    |

---

## 8) Solução de problemas

- **`whatsapp-web.js` não abre Chromium:** verifique se `chromium-browser` está instalado e ajuste `CHROMIUM_PATH`.
- **QR não aparece:** `sudo journalctl -u whatsflow-wa -f` para ver o log.
- **Sessão WhatsApp caiu:** delete `whatsapp-service/.wwebjs_auth/` e escaneie novamente.
- **Login painel.fun falhando:** confira a chave 2Captcha em Configurações. A conta 2Captcha precisa ter saldo (~$0.002 por login).
- **Nginx 502:** `sudo systemctl status whatsflow-backend` para checar o backend.

---

Pronto! Seu revendedor está no ar 🎉
