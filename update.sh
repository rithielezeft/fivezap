#!/usr/bin/env bash
# WhatsFlow — atualizador automático seguro
#
# Uso:
#   cd ~/WhatsFlow
#   sudo bash update.sh
#
# O que faz (nesta ordem):
#   1. Backup automático do banco SQLite + .env
#   2. Detecta o path real (case-insensitive) e o usuário do processo
#   3. Trata conflitos de git (whatsflow.db / .wwebjs_auth) com reset limpo
#   4. Puxa main do GitHub
#   5. Instala dependências no venv (PEP 668 safe) + Node (yarn)
#   6. Rebuilda o frontend se houver mudanças em frontend/
#   7. Reinicia o serviço systemd + valida health check
#   8. Rollback automático (git reset + restore DB) se health check falhar
#
# Idempotente: rodar 100 vezes seguidas é seguro.
set -euo pipefail

# ----- Detecção de contexto -----
if [ "$EUID" -ne 0 ]; then
  echo "❌ Rode como root:  sudo bash update.sh"
  exit 1
fi

APP_DIR="${APP_DIR:-$(pwd)}"
# Se o diretório atual não parece ser o repo, tenta descobrir
if [ ! -f "$APP_DIR/backend/server.py" ]; then
  for candidate in \
      "$HOME/WhatsFlow" "$HOME/whatsflow" \
      "/home/rithiele/WhatsFlow" "/home/rithiele/whatsflow" \
      "/home/pi/WhatsFlow" "/home/pi/whatsflow" \
      "/opt/whatsflow" "/opt/WhatsFlow"; do
    if [ -f "$candidate/backend/server.py" ]; then
      APP_DIR="$candidate"; break
    fi
  done
fi
if [ ! -f "$APP_DIR/backend/server.py" ]; then
  echo "❌ Não encontrei o repo WhatsFlow. Rode este script de dentro do repo."
  exit 1
fi

APP_USER="${SUDO_USER:-$(stat -c %U "$APP_DIR")}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/tmp/whatsflow-backup-${STAMP}"
LOG_FILE="/tmp/whatsflow-update-${STAMP}.log"

echo "════════════════════════════════════════════════" | tee -a "$LOG_FILE"
echo "  WhatsFlow Auto-Updater  ($STAMP)"                 | tee -a "$LOG_FILE"
echo "════════════════════════════════════════════════" | tee -a "$LOG_FILE"
echo "  APP_DIR:   $APP_DIR"       | tee -a "$LOG_FILE"
echo "  APP_USER:  $APP_USER"      | tee -a "$LOG_FILE"
echo "  BACKUP:    $BACKUP_DIR"    | tee -a "$LOG_FILE"
echo "  LOG:       $LOG_FILE"      | tee -a "$LOG_FILE"
echo                               | tee -a "$LOG_FILE"

cd "$APP_DIR"

# ----- 1) Backup -----
mkdir -p "$BACKUP_DIR"
echo "▶ Fazendo backup do estado atual..." | tee -a "$LOG_FILE"
[ -f backend/whatsflow.db ] && cp -f backend/whatsflow.db "$BACKUP_DIR/whatsflow.db"
[ -f backend/.env ]        && cp -f backend/.env        "$BACKUP_DIR/backend.env"
[ -f frontend/.env ]       && cp -f frontend/.env       "$BACKUP_DIR/frontend.env"
[ -d whatsapp-service/.wwebjs_auth ] && cp -r whatsapp-service/.wwebjs_auth "$BACKUP_DIR/wwebjs_auth" 2>/dev/null || true
CURRENT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
echo "  Commit atual: $CURRENT_COMMIT" | tee -a "$LOG_FILE"
echo "$CURRENT_COMMIT" > "$BACKUP_DIR/commit.txt"

# ----- 2) Limpar conflitos de git -----
echo "▶ Limpando estado sujo do git..." | tee -a "$LOG_FILE"
git merge --abort 2>/dev/null || true
git rebase --abort 2>/dev/null || true
git cherry-pick --abort 2>/dev/null || true

# Remove do índice tudo que deveria estar no gitignore mas foi commitado
for f in \
    backend/whatsflow.db backend/whatsflow.db-journal \
    backend/whatsflow.db-wal backend/whatsflow.db-shm \
    whatsapp-service/.wwebjs_auth whatsapp-service/.wwebjs_cache \
    whatsapp-service/node_modules backend/.venv frontend/build \
    frontend/node_modules; do
  git rm -rf --cached "$f" >/dev/null 2>&1 || true
done

# Reforça .gitignore
touch .gitignore
for pat in \
    "backend/whatsflow.db" \
    "backend/whatsflow.db-journal" \
    "backend/whatsflow.db-wal" \
    "backend/whatsflow.db-shm" \
    "backend/.venv/" \
    "backend/logs/" \
    "whatsapp-service/.wwebjs_auth/" \
    "whatsapp-service/.wwebjs_cache/" \
    "whatsapp-service/node_modules/" \
    "frontend/node_modules/" \
    "frontend/build/" \
    "*.log" \
    ".env" \
    "backend/.env" \
    "frontend/.env"; do
  grep -qxF "$pat" .gitignore 2>/dev/null || echo "$pat" >> .gitignore
done

# ----- 3) Puxar mudanças -----
echo "▶ Baixando atualizações do GitHub..." | tee -a "$LOG_FILE"
git stash push -u -m "auto-update-${STAMP}" 2>/dev/null || true

git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
[ "$BRANCH" = "HEAD" ] && BRANCH="main"

NEW_COMMIT="$(git rev-parse "origin/$BRANCH")"
if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
  echo "✅ Já está no commit mais recente ($NEW_COMMIT). Nada a atualizar." | tee -a "$LOG_FILE"
  echo "   (Prosseguindo com reinstalação de deps e restart mesmo assim.)"
fi

git reset --hard "origin/$BRANCH" | tee -a "$LOG_FILE"

# Restaura DB + .env preservados
[ -f "$BACKUP_DIR/whatsflow.db" ] && cp -f "$BACKUP_DIR/whatsflow.db" backend/whatsflow.db
[ -f "$BACKUP_DIR/backend.env"  ] && cp -f "$BACKUP_DIR/backend.env"  backend/.env
[ -f "$BACKUP_DIR/frontend.env" ] && cp -f "$BACKUP_DIR/frontend.env" frontend/.env

# Detecta se frontend mudou
FRONTEND_CHANGED=0
if [ "$CURRENT_COMMIT" != "unknown" ] && [ "$CURRENT_COMMIT" != "$NEW_COMMIT" ]; then
  if git diff --name-only "$CURRENT_COMMIT" "$NEW_COMMIT" | grep -q '^frontend/'; then
    FRONTEND_CHANGED=1
  fi
fi

# ----- 4) Backend deps (venv seguro contra PEP 668) -----
echo "▶ Instalando dependências Python no venv..." | tee -a "$LOG_FILE"
cd "$APP_DIR/backend"
if [ ! -d .venv ]; then
  sudo -u "$APP_USER" python3 -m venv .venv
fi
sudo -u "$APP_USER" ./.venv/bin/pip install --upgrade pip wheel --quiet 2>&1 | tee -a "$LOG_FILE" || true
sudo -u "$APP_USER" ./.venv/bin/pip install -r requirements.txt --quiet 2>&1 | tee -a "$LOG_FILE"
# Garante curl_cffi (bypass Cloudflare TLS)
sudo -u "$APP_USER" ./.venv/bin/pip install "curl_cffi>=0.7.4" --quiet 2>&1 | tee -a "$LOG_FILE" || true

# ----- 5) WhatsApp service deps -----
echo "▶ Instalando dependências Node do WhatsApp service..." | tee -a "$LOG_FILE"
cd "$APP_DIR/whatsapp-service"
sudo -u "$APP_USER" yarn install --ignore-engines --silent 2>&1 | tee -a "$LOG_FILE"

# ----- 6) Frontend (só rebuilda se mudou) -----
if [ "$FRONTEND_CHANGED" = "1" ] || [ ! -d "$APP_DIR/frontend/build" ]; then
  echo "▶ Rebuildando frontend..." | tee -a "$LOG_FILE"
  cd "$APP_DIR/frontend"
  sudo -u "$APP_USER" yarn install --silent 2>&1 | tee -a "$LOG_FILE"
  sudo -u "$APP_USER" yarn build 2>&1 | tee -a "$LOG_FILE"
  # nginx precisa ler o build
  chmod -R o+rX "$APP_DIR/frontend/build" 2>/dev/null || true
else
  echo "⏭  Frontend não mudou — pulando rebuild" | tee -a "$LOG_FILE"
fi

# ----- 7) Restart do serviço -----
echo "▶ Reiniciando whatsflow-backend..." | tee -a "$LOG_FILE"
systemctl restart whatsflow-backend
sleep 5

# ----- 8) Health check -----
echo "▶ Verificando saúde do serviço..." | tee -a "$LOG_FILE"
HEALTH_OK=0
for i in 1 2 3 4 5; do
  if curl -sf --max-time 5 http://localhost:8001/api/health >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  echo "   tentativa $i/5..." | tee -a "$LOG_FILE"
  sleep 3
done

if [ "$HEALTH_OK" = "1" ]; then
  echo ""                                             | tee -a "$LOG_FILE"
  echo "✅ ATUALIZAÇÃO COMPLETA — serviço saudável!"  | tee -a "$LOG_FILE"
  echo "   Commit: $NEW_COMMIT"                       | tee -a "$LOG_FILE"
  echo "   Backup preservado em: $BACKUP_DIR"         | tee -a "$LOG_FILE"
  echo "   Log completo: $LOG_FILE"                   | tee -a "$LOG_FILE"

  # Limpa backups velhos (mais de 7 dias)
  find /tmp -maxdepth 1 -name "whatsflow-backup-*" -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
  find /tmp -maxdepth 1 -name "whatsflow-update-*.log" -mtime +7 -delete 2>/dev/null || true
  exit 0
fi

# ----- ROLLBACK -----
echo "❌ Health check falhou! Fazendo rollback para $CURRENT_COMMIT..." | tee -a "$LOG_FILE"
cd "$APP_DIR"
git reset --hard "$CURRENT_COMMIT" | tee -a "$LOG_FILE"
[ -f "$BACKUP_DIR/whatsflow.db" ] && cp -f "$BACKUP_DIR/whatsflow.db" backend/whatsflow.db
[ -f "$BACKUP_DIR/backend.env"  ] && cp -f "$BACKUP_DIR/backend.env"  backend/.env
systemctl restart whatsflow-backend
sleep 5
if curl -sf --max-time 5 http://localhost:8001/api/health >/dev/null 2>&1; then
  echo "🔙 Rollback bem-sucedido. Verifique o log: $LOG_FILE" | tee -a "$LOG_FILE"
else
  echo "🚨 ROLLBACK FALHOU — investigue manualmente!" | tee -a "$LOG_FILE"
  echo "   journalctl -u whatsflow-backend -n 100"    | tee -a "$LOG_FILE"
fi
exit 1
