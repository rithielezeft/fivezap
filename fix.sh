#!/usr/bin/env bash
# WhatsFlow — Script de manutenção pós git pull.
# Corrige os problemas conhecidos:
#   1. Remove .wwebjs_auth commitado por engano no repo antigo
#   2. Garante que curl_cffi está instalado
#   3. Cria diretório de sessão em $HOME/.whatsflow/
#   4. Restart do serviço
#
# Uso:  bash fix.sh
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "▶ Diretório: $APP_DIR"

# 1. Remove .wwebjs_auth tracked no git (se ainda estiver)
cd "$APP_DIR"
if git ls-files --error-unmatch whatsapp-service/.wwebjs_auth >/dev/null 2>&1; then
  echo "▶ Removendo .wwebjs_auth do tracking git..."
  git rm -rf --cached whatsapp-service/.wwebjs_auth 2>/dev/null || true
  git commit -m "chore: untrack wwebjs session dir" --allow-empty || true
fi

# 2. Remove qualquer .wwebjs_auth local (limpa cache velho com paths /app/)
rm -rf whatsapp-service/.wwebjs_auth whatsapp-service/.wwebjs_cache 2>/dev/null || true

# 3. Cria diretório novo em $HOME (fora do repo)
mkdir -p "$HOME/.whatsflow/wwebjs_auth"
echo "▶ Sessão WhatsApp agora em: $HOME/.whatsflow/wwebjs_auth"

# 4. Instala curl_cffi se necessário (bypass TLS do painel.fun)
if [ -f "$APP_DIR/backend/.venv/bin/pip" ]; then
  echo "▶ Verificando curl_cffi..."
  "$APP_DIR/backend/.venv/bin/pip" install curl_cffi==0.7.4 --quiet 2>&1 | tail -3 || true
fi

# 5. Restart
echo "▶ Reiniciando backend..."
sudo systemctl restart whatsflow-backend
sleep 5

echo
echo "✅ Manutenção concluída."
echo "   Sessão WhatsApp: $HOME/.whatsflow/wwebjs_auth"
echo "   Logs:            $APP_DIR/backend/logs/whatsapp-service.out.log"
echo
echo "Testa em: https://whatsflow.zeferius.com/whatsapp"
