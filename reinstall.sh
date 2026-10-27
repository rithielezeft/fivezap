#!/usr/bin/env bash
# WhatsFlow — deploy limpo do ZERO (nuclear reset).
#
# Uso:
#   cd ~/WhatsFlow
#   sudo bash reinstall.sh
#
# Faz backup do banco + sessão do WhatsApp, apaga todo o estado (node_modules,
# venv, build, cache) e recria tudo. Use quando quiser garantir um estado
# 100% consistente (ex: mudança grande de dependências, corrupção de venv).
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "❌ Rode como root:  sudo bash reinstall.sh"
  exit 1
fi

APP_DIR="${APP_DIR:-$(pwd)}"
if [ ! -f "$APP_DIR/backend/server.py" ]; then
  echo "❌ Rode este script de dentro do repo WhatsFlow."
  exit 1
fi

APP_USER="${SUDO_USER:-$(stat -c %U "$APP_DIR")}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/tmp/whatsflow-full-backup-${STAMP}"

echo "════════════════════════════════════════════════"
echo "  WhatsFlow REINSTALL (limpeza total)  $STAMP"
echo "════════════════════════════════════════════════"
echo "  APP_DIR:  $APP_DIR"
echo "  APP_USER: $APP_USER"
echo "  BACKUP:   $BACKUP_DIR"
echo

read -r -p "⚠️  Isso vai APAGAR node_modules, venv, build e reinstalar tudo. Continuar? (s/N) " ans
[ "${ans:-}" != "s" ] && [ "${ans:-}" != "S" ] && { echo "Abortado."; exit 0; }

mkdir -p "$BACKUP_DIR"
echo "▶ Backup completo..."
[ -f backend/whatsflow.db ] && cp -f backend/whatsflow.db "$BACKUP_DIR/whatsflow.db"
[ -f backend/.env ]        && cp -f backend/.env        "$BACKUP_DIR/backend.env"
[ -f frontend/.env ]       && cp -f frontend/.env       "$BACKUP_DIR/frontend.env"
[ -d whatsapp-service/.wwebjs_auth ] && cp -r whatsapp-service/.wwebjs_auth "$BACKUP_DIR/wwebjs_auth" 2>/dev/null || true

echo "▶ Parando serviço..."
systemctl stop whatsflow-backend 2>/dev/null || true

echo "▶ Apagando estado gerado..."
rm -rf "$APP_DIR/backend/.venv"
rm -rf "$APP_DIR/backend/__pycache__"
find "$APP_DIR/backend" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rm -rf "$APP_DIR/whatsapp-service/node_modules"
rm -rf "$APP_DIR/whatsapp-service/.wwebjs_cache"
rm -rf "$APP_DIR/frontend/node_modules"
rm -rf "$APP_DIR/frontend/build"
rm -rf "$APP_DIR/frontend/.cache"

echo "▶ Puxando última versão do main..."
cd "$APP_DIR"
git merge --abort 2>/dev/null || true
git fetch origin
git reset --hard origin/main

echo "▶ Restaurando DB + .env..."
[ -f "$BACKUP_DIR/whatsflow.db" ] && cp -f "$BACKUP_DIR/whatsflow.db" backend/whatsflow.db
[ -f "$BACKUP_DIR/backend.env"  ] && cp -f "$BACKUP_DIR/backend.env"  backend/.env
[ -f "$BACKUP_DIR/frontend.env" ] && cp -f "$BACKUP_DIR/frontend.env" frontend/.env
[ -d "$BACKUP_DIR/wwebjs_auth"  ] && cp -r "$BACKUP_DIR/wwebjs_auth" whatsapp-service/.wwebjs_auth

echo "▶ Recriando venv Python..."
cd "$APP_DIR/backend"
sudo -u "$APP_USER" python3 -m venv .venv
sudo -u "$APP_USER" ./.venv/bin/pip install --upgrade pip wheel
sudo -u "$APP_USER" ./.venv/bin/pip install -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
sudo -u "$APP_USER" ./.venv/bin/pip install "curl_cffi>=0.7.4"

echo "▶ Reinstalando WhatsApp service (Node)..."
cd "$APP_DIR/whatsapp-service"
sudo -u "$APP_USER" yarn install --ignore-engines

echo "▶ Rebuild do frontend..."
cd "$APP_DIR/frontend"
sudo -u "$APP_USER" yarn install
sudo -u "$APP_USER" yarn build
chmod -R o+rX "$APP_DIR/frontend/build" 2>/dev/null || true

echo "▶ Restart do serviço..."
systemctl restart whatsflow-backend
sleep 5

if curl -sf --max-time 5 http://localhost:8001/api/health >/dev/null 2>&1; then
  echo ""
  echo "✅ REINSTALL COMPLETA — tudo funcionando!"
  echo "   Backup em: $BACKUP_DIR"
else
  echo ""
  echo "❌ Serviço não respondeu ao health check."
  echo "   Veja: sudo journalctl -u whatsflow-backend -n 100"
  exit 1
fi
