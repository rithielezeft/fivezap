#!/usr/bin/env bash
# WhatsFlow — instalador automático para Raspberry Pi (Raspberry Pi OS 64-bit)
#
# Uso:
#   cd ~/WhatsFlow
#   sudo bash install.sh
#
# O script:
#   1. Instala dependências do sistema (Python, Node, Chromium, nginx)
#   2. Cria virtualenv e instala pacotes Python
#   3. Instala dependências Node do serviço WhatsApp e faz build do frontend
#   4. Gera arquivos .env com JWT_SECRET aleatório
#   5. Cria serviços systemd para rodar tudo em background 24/7
#   6. Configura nginx como reverse proxy
#
# Depois de rodar, acesse http://<ip-da-raspberry>/ e faça login com Rithi0518@

set -e

if [ "$EUID" -ne 0 ]; then
  echo "❌ Rode como root: sudo bash install.sh"
  exit 1
fi

# --- Configurações padrão (podem ser sobrescritas via env) ---
APP_DIR="${APP_DIR:-$(pwd)}"
APP_USER="${SUDO_USER:-pi}"
APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
DOMAIN="${DOMAIN:-}"       # ex: whatsflow.zeferius.com
ADMIN_PW="${ADMIN_PW:-Rithi0518@}"

echo "════════════════════════════════════════════════"
echo "  WhatsFlow Installer"
echo "════════════════════════════════════════════════"
echo "  Diretório:     $APP_DIR"
echo "  Usuário:       $APP_USER"
echo "  Home:          $APP_HOME"
echo "  Domínio HTTPS: ${DOMAIN:-<nenhum — só HTTP na porta 80>}"
echo "════════════════════════════════════════════════"
echo

# ------------------------------------------------------------------
# 1) Dependências do sistema
# ------------------------------------------------------------------
echo "▶ Instalando dependências do sistema..."
apt update
apt install -y \
  python3 python3-pip python3-venv \
  curl git openssl \
  nginx \
  libnss3 libatk-bridge2.0-0 libx11-xcb1 libxcomposite1 libxrandr2 \
  libxdamage1 libxfixes3 libxi6 libgbm1 libpangocairo-1.0-0 libasound2

# Chromium (Raspberry Pi OS pode ter chromium OU chromium-browser)
if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  apt install -y chromium || apt install -y chromium-browser || true
fi

# Detecta o caminho real do Chromium
CHROMIUM_BIN=$(command -v chromium-browser || command -v chromium || echo "/usr/bin/chromium")
echo "  ✓ Chromium: $CHROMIUM_BIN"

# Instala Node.js 20 se não estiver disponível
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | grep -oE '[0-9]+' | head -1)" -lt 18 ]; then
  echo "▶ Instalando Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
fi

# Instala yarn se não tiver
if ! command -v yarn >/dev/null 2>&1; then
  echo "▶ Instalando yarn..."
  npm install -g yarn
fi

# ------------------------------------------------------------------
# 2) Backend — venv + pip install
# ------------------------------------------------------------------
echo "▶ Instalando backend Python..."
cd "$APP_DIR/backend"

sudo -u "$APP_USER" python3 -m venv .venv
sudo -u "$APP_USER" ./.venv/bin/pip install --upgrade pip wheel
sudo -u "$APP_USER" ./.venv/bin/pip install -r requirements.txt

# Gera .env se não existir
if [ ! -f .env ]; then
  JWT=$(openssl rand -hex 64)
  cat > .env <<EOF
MONGO_URL="mongodb://localhost:27017"
DB_NAME="whatsflow"
CORS_ORIGINS="*"
JWT_SECRET="$JWT"
ADMIN_PASSWORD="$ADMIN_PW"
EOF
  chown "$APP_USER":"$APP_USER" .env
  echo "  ✓ backend/.env criado (senha admin: $ADMIN_PW)"
fi

# ------------------------------------------------------------------
# 3) WhatsApp service — yarn install
# ------------------------------------------------------------------
echo "▶ Instalando serviço WhatsApp (Node.js)..."
cd "$APP_DIR/whatsapp-service"
sudo -u "$APP_USER" yarn install --ignore-engines

# ------------------------------------------------------------------
# 4) Frontend — install + build
# ------------------------------------------------------------------
echo "▶ Instalando e buildando o frontend..."
cd "$APP_DIR/frontend"

# .env do frontend
if [ ! -f .env ]; then
  if [ -n "$DOMAIN" ]; then
    URL="https://$DOMAIN"
  else
    URL="http://$(hostname -I | awk '{print $1}')"
  fi
  echo "REACT_APP_BACKEND_URL=$URL" > .env
  chown "$APP_USER":"$APP_USER" .env
  echo "  ✓ frontend/.env criado (backend URL: $URL)"
fi

sudo -u "$APP_USER" yarn install
sudo -u "$APP_USER" yarn build

# ------------------------------------------------------------------
# 5) Systemd services
# ------------------------------------------------------------------
echo "▶ Criando serviços systemd..."

cat > /etc/systemd/system/whatsflow-backend.service <<EOF
[Unit]
Description=WhatsFlow Backend (FastAPI)
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR/backend
Environment="PATH=$APP_DIR/backend/.venv/bin:/usr/bin:/bin"
Environment="CHROMIUM_PATH=$CHROMIUM_BIN"
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# O backend faz spawn automático do serviço whatsapp-web.js na inicialização,
# mas se quiser rodar em separado, crie whatsflow-wa.service e desative o
# _start_whatsapp_service() no backend/server.py.

# ------------------------------------------------------------------
# 6) Nginx reverse proxy
# ------------------------------------------------------------------
echo "▶ Configurando nginx..."

SERVER_NAME="_"
if [ -n "$DOMAIN" ]; then
  SERVER_NAME="$DOMAIN"
fi

cat > /etc/nginx/sites-available/whatsflow <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    client_max_body_size 20M;

    # Frontend (React build)
    root $APP_DIR/frontend/build;
    index index.html;

    location / {
        try_files \$uri /index.html;
    }

    # API + uploads → backend :8001
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 60s;
    }
}
EOF

# Ativa o site
ln -sf /etc/nginx/sites-available/whatsflow /etc/nginx/sites-enabled/whatsflow
rm -f /etc/nginx/sites-enabled/default

# Verifica se a porta 80 está sendo usada por outro serviço
if ss -tlnp 2>/dev/null | grep -q ':80 '; then
  if ! ss -tlnp 2>/dev/null | grep ':80 ' | grep -q nginx; then
    echo "  ⚠ Porta 80 já em uso por outro serviço. Verifique com: sudo ss -tlnp | grep :80"
    echo "     Se for Apache, pare com: sudo systemctl stop apache2 && sudo systemctl disable apache2"
  fi
fi

nginx -t
systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || echo "  ⚠ Nginx falhou ao iniciar. Rode: sudo systemctl status nginx"

# ------------------------------------------------------------------
# 7) Ativa e sobe tudo
# ------------------------------------------------------------------
echo "▶ Iniciando serviços..."
systemctl daemon-reload
systemctl enable whatsflow-backend nginx
systemctl restart whatsflow-backend
systemctl enable nginx

# ------------------------------------------------------------------
# 8) HTTPS (opcional)
# ------------------------------------------------------------------
if [ -n "$DOMAIN" ]; then
  echo "▶ Configurando HTTPS com Let's Encrypt para $DOMAIN..."
  apt install -y certbot python3-certbot-nginx
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" --redirect || \
    echo "  ⚠ Não foi possível emitir certificado (o domínio aponta pra este IP?). Rode manualmente: sudo certbot --nginx -d $DOMAIN"
fi

# ------------------------------------------------------------------
# 9) Backup diário
# ------------------------------------------------------------------
echo "▶ Configurando backup diário do SQLite..."
cat > /etc/cron.daily/whatsflow-backup <<EOF
#!/bin/bash
mkdir -p $APP_HOME/backups
cp $APP_DIR/backend/whatsflow.db $APP_HOME/backups/whatsflow-\$(date +%Y%m%d).db 2>/dev/null || true
find $APP_HOME/backups -name "whatsflow-*.db" -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/whatsflow-backup

# ------------------------------------------------------------------
# Fim!
# ------------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
echo
echo "════════════════════════════════════════════════"
echo "  ✅ WhatsFlow instalado com sucesso!"
echo "════════════════════════════════════════════════"
echo
if [ -n "$DOMAIN" ]; then
  echo "  🌐 Acesse: https://$DOMAIN/login"
else
  echo "  🌐 Acesse: http://$IP/login"
fi
echo "  🔑 Senha:  $ADMIN_PW  (troque na página Configurações)"
echo
echo "  📋 Próximos passos:"
echo "    1. Faça login"
echo "    2. Vá em WhatsApp e escaneie o QR code"
echo "    3. Vá em Configurações e preencha o InfiniteTag do InfinitePay"
echo "    4. Personalize os templates em Notificações"
echo
echo "  📝 Logs em tempo real:"
echo "    sudo journalctl -u whatsflow-backend -f"
echo "    tail -f /var/log/whatsapp-service.out.log"
echo
echo "  🔁 Restart:  sudo systemctl restart whatsflow-backend nginx"
echo "════════════════════════════════════════════════"
