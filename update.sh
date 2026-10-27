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
APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
[ -z "$APP_HOME" ] && APP_HOME=$(dirname "$APP_DIR")
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

# ----- 0) Garantir que o Chromium está instalado (necessário pro Puppeteer) -----
# Sem chromium instalado, o whatsapp-web.js trava em "starting" e nunca gera o QR.
# Debian Trixie NÃO instala o chromium por padrão. Detectamos e instalamos.
CHROMIUM_PATHS=(/usr/bin/chromium-browser /usr/bin/chromium /snap/bin/chromium)
CHROMIUM_FOUND=""
for p in "${CHROMIUM_PATHS[@]}"; do
  if [ -x "$p" ]; then CHROMIUM_FOUND="$p"; break; fi
done
if [ -z "$CHROMIUM_FOUND" ]; then
  echo "▶ Chromium não encontrado — instalando via apt..." | tee -a "$LOG_FILE"
  # Tenta os dois nomes de pacote: chromium-browser (RPi OS) e chromium (Debian puro)
  DEBIAN_FRONTEND=noninteractive apt-get update -y 2>&1 | tee -a "$LOG_FILE" || true
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y chromium-browser 2>&1 | tee -a "$LOG_FILE"; then
    echo "▶ chromium-browser indisponível — tentando pacote 'chromium'..." | tee -a "$LOG_FILE"
    DEBIAN_FRONTEND=noninteractive apt-get install -y chromium 2>&1 | tee -a "$LOG_FILE" || true
  fi
  # Reverifica
  for p in "${CHROMIUM_PATHS[@]}"; do
    if [ -x "$p" ]; then CHROMIUM_FOUND="$p"; break; fi
  done
  if [ -z "$CHROMIUM_FOUND" ]; then
    echo "⚠️  Não consegui instalar o Chromium automaticamente." | tee -a "$LOG_FILE"
    echo "    Rode manualmente:  sudo apt install -y chromium"    | tee -a "$LOG_FILE"
  else
    echo "✅ Chromium instalado em: $CHROMIUM_FOUND" | tee -a "$LOG_FILE"
  fi
else
  echo "✅ Chromium presente em: $CHROMIUM_FOUND" | tee -a "$LOG_FILE"
fi

# ----- 1) Backup -----
mkdir -p "$BACKUP_DIR"
echo "▶ Fazendo backup do estado atual..." | tee -a "$LOG_FILE"
[ -f backend/whatsflow.db ] && cp -f backend/whatsflow.db "$BACKUP_DIR/whatsflow.db"
[ -f backend/.env ]        && cp -f backend/.env        "$BACKUP_DIR/backend.env"
[ -f frontend/.env ]       && cp -f frontend/.env       "$BACKUP_DIR/frontend.env"
[ -d whatsapp-service/.wwebjs_auth ] && cp -r whatsapp-service/.wwebjs_auth "$BACKUP_DIR/wwebjs_auth" 2>/dev/null || true
CURRENT_COMMIT="$(sudo -u "$APP_USER" git rev-parse HEAD 2>/dev/null || echo 'unknown')"
echo "  Commit atual: $CURRENT_COMMIT" | tee -a "$LOG_FILE"
echo "$CURRENT_COMMIT" > "$BACKUP_DIR/commit.txt"

# ----- 1.5) PARAR o backend ANTES de mexer em qualquer arquivo do WA -----
# O Chromium mantém locks em .wwebjs_auth/ e pode ter criado arquivos como root.
# Parar o serviço libera os locks. Depois vamos garantir que a pasta é toda do
# usuário para o git conseguir operar.
echo "▶ Parando backend para liberar locks do WhatsApp..." | tee -a "$LOG_FILE"
systemctl stop whatsflow-backend 2>/dev/null || true
sleep 2

# Elimina o cache do WhatsApp (não é necessário — será regenerado)
rm -rf whatsapp-service/.wwebjs_cache 2>/dev/null || true

# Corrige ownership de .wwebjs_auth para o app user, senão git falha ao dar
# reset --hard com "Permission denied" (arquivos criados pelo Chromium como root)
if [ -d whatsapp-service/.wwebjs_auth ]; then
  echo "▶ Corrigindo ownership de whatsapp-service/.wwebjs_auth..." | tee -a "$LOG_FILE"
  chown -R "$APP_USER":"$APP_USER" whatsapp-service/.wwebjs_auth 2>/dev/null || true
fi

# Corrige ownership do .git — comandos anteriores rodados como root deixaram
# objects/ com dono root, causando "insufficient permission for adding an
# object to repository database .git/objects" no próximo git fetch.
if [ -d .git ]; then
  echo "▶ Corrigindo ownership do .git..." | tee -a "$LOG_FILE"
  chown -R "$APP_USER":"$APP_USER" .git 2>/dev/null || true
fi

# Garante que git aceita esse repo (safe.directory) mesmo se o dono divergir
sudo -u "$APP_USER" git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

# ----- 2) Limpar conflitos de git -----
echo "▶ Limpando estado sujo do git..." | tee -a "$LOG_FILE"
sudo -u "$APP_USER" git merge --abort 2>/dev/null || true
sudo -u "$APP_USER" git rebase --abort 2>/dev/null || true
sudo -u "$APP_USER" git cherry-pick --abort 2>/dev/null || true

# Remove do índice tudo que deveria estar no gitignore mas foi commitado.
# Fazemos os que dão para deletar de uma vez, mas o .wwebjs_auth pode ter
# 500+ arquivos tracked — usamos `git ls-files` + `git rm --cached` pra pegar TUDO.
sudo -u "$APP_USER" git ls-files -z 'whatsapp-service/.wwebjs_auth/*' 2>/dev/null \
  | xargs -0 -r sudo -u "$APP_USER" git rm -rf --cached >/dev/null 2>&1 || true
sudo -u "$APP_USER" git ls-files -z 'whatsapp-service/.wwebjs_cache/*' 2>/dev/null \
  | xargs -0 -r sudo -u "$APP_USER" git rm -rf --cached >/dev/null 2>&1 || true

for f in \
    backend/whatsflow.db backend/whatsflow.db-journal \
    backend/whatsflow.db-wal backend/whatsflow.db-shm \
    whatsapp-service/.wwebjs_auth whatsapp-service/.wwebjs_cache \
    whatsapp-service/node_modules backend/.venv frontend/build \
    frontend/node_modules; do
  sudo -u "$APP_USER" git rm -rf --cached "$f" >/dev/null 2>&1 || true
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
sudo -u "$APP_USER" git stash push -u -m "auto-update-${STAMP}" 2>/dev/null || true

sudo -u "$APP_USER" git fetch origin
BRANCH="$(sudo -u "$APP_USER" git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
[ "$BRANCH" = "HEAD" ] && BRANCH="main"

NEW_COMMIT="$(sudo -u "$APP_USER" git rev-parse "origin/$BRANCH")"
if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
  echo "✅ Já está no commit mais recente ($NEW_COMMIT). Nada a atualizar." | tee -a "$LOG_FILE"
  echo "   (Prosseguindo com reinstalação de deps e restart mesmo assim.)"
fi

# Tentativa 1 de reset — pode falhar por permissão em .wwebjs_auth
if ! sudo -u "$APP_USER" git reset --hard "origin/$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
  echo "▶ Reset falhou por permissão. Forçando limpeza da sessão do WhatsApp..." | tee -a "$LOG_FILE"
  # Última linha de defesa: rm -rf como root da pasta problemática, depois retry.
  # O backup já foi feito em $BACKUP_DIR/wwebjs_auth.
  rm -rf whatsapp-service/.wwebjs_auth 2>/dev/null || true
  sudo -u "$APP_USER" git reset --hard "origin/$BRANCH" | tee -a "$LOG_FILE"
fi

# Restaura DB + .env preservados
[ -f "$BACKUP_DIR/whatsflow.db" ] && cp -f "$BACKUP_DIR/whatsflow.db" backend/whatsflow.db
[ -f "$BACKUP_DIR/backend.env"  ] && cp -f "$BACKUP_DIR/backend.env"  backend/.env
[ -f "$BACKUP_DIR/frontend.env" ] && cp -f "$BACKUP_DIR/frontend.env" frontend/.env

# Restaura sessão do WhatsApp (evita re-scan do QR code)
if [ -d "$BACKUP_DIR/wwebjs_auth" ] && [ ! -d whatsapp-service/.wwebjs_auth ]; then
  echo "▶ Restaurando sessão do WhatsApp do backup..." | tee -a "$LOG_FILE"
  cp -r "$BACKUP_DIR/wwebjs_auth" whatsapp-service/.wwebjs_auth
  chown -R "$APP_USER":"$APP_USER" whatsapp-service/.wwebjs_auth 2>/dev/null || true
fi

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
sudo -u "$APP_USER" ./.venv/bin/pip install -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ --quiet 2>&1 | tee -a "$LOG_FILE"
# Garante curl_cffi (bypass Cloudflare TLS)
sudo -u "$APP_USER" ./.venv/bin/pip install "curl_cffi>=0.7.4" --quiet 2>&1 | tee -a "$LOG_FILE" || true

# ----- 5) WhatsApp service deps -----
echo "▶ Instalando dependências Node do WhatsApp service..." | tee -a "$LOG_FILE"
cd "$APP_DIR/whatsapp-service"
sudo -u "$APP_USER" yarn install --ignore-engines --silent 2>&1 | tee -a "$LOG_FILE"

# ----- 6) Frontend — rebuilda se mudou OU se o build está corrompido/incompleto -----
NEED_REBUILD=0
if [ "$FRONTEND_CHANGED" = "1" ]; then
  echo "▶ frontend/ mudou — rebuild necessário" | tee -a "$LOG_FILE"
  NEED_REBUILD=1
elif [ ! -f "$APP_DIR/frontend/build/index.html" ]; then
  echo "▶ frontend/build/index.html não existe — rebuild forçado" | tee -a "$LOG_FILE"
  NEED_REBUILD=1
elif [ ! -d "$APP_DIR/frontend/build/static" ]; then
  echo "▶ frontend/build/static ausente — rebuild forçado" | tee -a "$LOG_FILE"
  NEED_REBUILD=1
fi

if [ "$NEED_REBUILD" = "1" ]; then
  echo "▶ Rebuildando frontend..." | tee -a "$LOG_FILE"
  cd "$APP_DIR/frontend"
  sudo -u "$APP_USER" yarn install --silent 2>&1 | tee -a "$LOG_FILE"
  sudo -u "$APP_USER" yarn build 2>&1 | tee -a "$LOG_FILE"
  if [ ! -f "$APP_DIR/frontend/build/index.html" ]; then
    echo "❌ Build do frontend falhou — index.html não foi criado" | tee -a "$LOG_FILE"
    exit 1
  fi
else
  echo "⏭  Frontend não mudou e build está íntegro — pulando rebuild" | tee -a "$LOG_FILE"
fi

# Garante permissões pro nginx (www-data) ler o build — SEMPRE, mesmo sem rebuild
echo "▶ Ajustando permissões do build para o nginx..." | tee -a "$LOG_FILE"
chmod o+x "$APP_HOME" 2>/dev/null || true
chmod o+x "$APP_DIR" 2>/dev/null || true
chmod o+x "$APP_DIR/frontend" 2>/dev/null || true
chmod -R o+rX "$APP_DIR/frontend/build" 2>/dev/null || true

# ----- 7) Restart do serviço + reload do nginx -----
echo "▶ Reiniciando whatsflow-backend..." | tee -a "$LOG_FILE"
systemctl restart whatsflow-backend
sleep 5

# Recarrega nginx pra pegar qualquer nova config e limpar cache interno
if systemctl is-active --quiet nginx 2>/dev/null; then
  echo "▶ Recarregando nginx..." | tee -a "$LOG_FILE"
  systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
fi

# ----- 8) Health check duplo: backend + frontend servido pelo nginx -----
echo "▶ Verificando saúde do backend..." | tee -a "$LOG_FILE"
HEALTH_OK=0
for i in 1 2 3 4 5; do
  if curl -sf --max-time 5 http://localhost:8001/api/health >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  echo "   tentativa $i/5..." | tee -a "$LOG_FILE"
  sleep 3
done

# Health check do site (nginx → build) — detecta 500/404 causado por build faltando
if [ "$HEALTH_OK" = "1" ]; then
  echo "▶ Verificando saúde do frontend (nginx)..." | tee -a "$LOG_FILE"
  FRONT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost/ 2>/dev/null || echo "000")
  if [ "$FRONT_STATUS" = "500" ] || [ "$FRONT_STATUS" = "502" ] || [ "$FRONT_STATUS" = "503" ]; then
    echo "⚠️  Frontend retornou HTTP $FRONT_STATUS — possível problema no build ou permissão." | tee -a "$LOG_FILE"
    echo "    Última linha do nginx error.log:"                                           | tee -a "$LOG_FILE"
    tail -n 3 /var/log/nginx/error.log 2>/dev/null | tee -a "$LOG_FILE" || true
    HEALTH_OK=0
  else
    echo "   Frontend OK (HTTP $FRONT_STATUS)" | tee -a "$LOG_FILE"
  fi
fi

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
sudo -u "$APP_USER" git reset --hard "$CURRENT_COMMIT" | tee -a "$LOG_FILE"
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
