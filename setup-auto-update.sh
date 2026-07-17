#!/usr/bin/env bash
# WhatsFlow — instala um timer systemd para auto-update diário.
#
# Uso:
#   sudo bash setup-auto-update.sh          # instala e ativa
#   sudo bash setup-auto-update.sh disable  # desativa
#
# Por padrão roda TODO DIA às 04:30 da manhã (horário do Pi).
# Ajuste em /etc/systemd/system/whatsflow-update.timer se quiser outro horário.

set -e
if [ "$EUID" -ne 0 ]; then
  echo "❌ Rode como root: sudo bash setup-auto-update.sh"
  exit 1
fi

APP_DIR="${APP_DIR:-$(pwd)}"
if [ ! -f "$APP_DIR/update.sh" ]; then
  echo "❌ update.sh não encontrado em $APP_DIR. Rode dentro do repo WhatsFlow."
  exit 1
fi

if [ "${1:-}" = "disable" ]; then
  systemctl disable --now whatsflow-update.timer 2>/dev/null || true
  systemctl disable whatsflow-update.service 2>/dev/null || true
  rm -f /etc/systemd/system/whatsflow-update.timer /etc/systemd/system/whatsflow-update.service
  systemctl daemon-reload
  echo "✅ Auto-update desativado."
  exit 0
fi

cat > /etc/systemd/system/whatsflow-update.service <<EOF
[Unit]
Description=WhatsFlow Auto-Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/update.sh
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/whatsflow-update.timer <<'EOF'
[Unit]
Description=WhatsFlow Auto-Update daily
Requires=whatsflow-update.service

[Timer]
OnCalendar=*-*-* 04:30:00
Persistent=true
RandomizedDelaySec=15min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now whatsflow-update.timer

echo "✅ Auto-update ativado! Vai rodar todo dia às 04:30."
echo "   Verificar próxima execução: systemctl list-timers whatsflow-update.timer"
echo "   Ver logs:                    journalctl -u whatsflow-update.service -n 50"
echo "   Rodar agora manualmente:     sudo systemctl start whatsflow-update.service"
echo "   Desativar:                   sudo bash setup-auto-update.sh disable"
