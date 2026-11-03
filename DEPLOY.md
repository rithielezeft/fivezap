# 🚀 WhatsFlow — Guia de Deploy no Raspberry Pi

Três formas de subir/atualizar o WhatsFlow no seu Pi, do mais simples ao mais robusto.

---

## ⚡ Opção 1 — Update rápido (recomendado para o dia-a-dia)

Já tem o WhatsFlow rodando via systemd? Toda vez que quiser puxar as novas mudanças:

```bash
cd ~/WhatsFlow
sudo bash update.sh
```

O `update.sh` faz TUDO automaticamente:

- ✅ Backup automático (`whatsflow.db`, `.env`, sessão WhatsApp) em `/tmp/whatsflow-backup-*`
- ✅ Limpa conflitos de git dos arquivos binários (o problema que você teve)
- ✅ Puxa main do GitHub
- ✅ Reinstala deps Python **no venv** (PEP 668 safe — sem `--break-system-packages`)
- ✅ Reinstala deps Node do WhatsApp service
- ✅ **Rebuilda o frontend SÓ se `frontend/` mudou** (economiza tempo em updates de backend)
- ✅ Reinicia `whatsflow-backend` + valida `/api/health`
- ✅ **Rollback automático** se o health check falhar

**Log completo em** `/tmp/whatsflow-update-*.log`.

---

## 🤖 Opção 2 — Atualização automática diária

Instala um systemd timer que roda `update.sh` toda madrugada às 04:30:

```bash
cd ~/WhatsFlow
sudo bash setup-auto-update.sh
```

Verificar status:
```bash
systemctl list-timers whatsflow-update.timer
journalctl -u whatsflow-update.service -n 50
```

Rodar agora manualmente:
```bash
sudo systemctl start whatsflow-update.service
```

Desativar:
```bash
sudo bash setup-auto-update.sh disable
```

---

## 💣 Opção 3 — Reset limpo (nuclear)

Quando algo ficar realmente inconsistente (venv corrompido, node_modules zoado, cache do build travado):

```bash
cd ~/WhatsFlow
sudo bash reinstall.sh
```

Isso:
1. Faz backup completo (DB, envs, sessão WhatsApp) em `/tmp/whatsflow-full-backup-*`
2. Para o serviço
3. **Apaga** `.venv`, `node_modules`, `frontend/build`, `__pycache__`, `.wwebjs_cache`
4. `git reset --hard origin/main`
5. Restaura DB + .env + sessão WhatsApp
6. Recria venv, reinstala tudo, rebuild
7. Restart + health check

---

## 🐳 Opção 4 — Docker Compose (experimental para ARM64)

Se um dia quiser rodar tudo em containers isolados (útil se tiver múltiplos apps no mesmo Pi):

```bash
cd ~/WhatsFlow
cp .env.example .env
nano .env    # ajuste JWT_SECRET (openssl rand -hex 64), ADMIN_PASSWORD, REACT_APP_BACKEND_URL

# Sobe os 3 containers (backend + whatsapp + frontend)
sudo docker compose up -d --build

# Para atualizar depois:
git pull origin main
sudo docker compose up -d --build

# Ver logs:
sudo docker compose logs -f backend
sudo docker compose logs -f whatsapp
```

**Volumes persistentes** (nada perdido em rebuilds):
- `./data/db/` — SQLite
- `./data/wa_auth/` — sessão WhatsApp (não pede QR de novo)
- `./data/uploads/` — uploads de imagens

**Nota**: o WhatsApp usa Puppeteer/Chromium. Em Pi Zero/1/2 pode ficar lento; Pi 3+ funciona.

---

## 🧯 Troubleshooting

### `pip install ... externally-managed-environment` (PEP 668)
Isso acontece quando você roda `pip` fora do venv no Raspberry Pi OS Bookworm+.
**Solução**: sempre use `update.sh` — ele usa `./.venv/bin/pip` automaticamente.

Se precisar rodar manual:
```bash
cd ~/WhatsFlow/backend
./.venv/bin/pip install -r requirements.txt
```

### `whatsflow-whatsapp.service not found`
Isso está correto — não existe um systemd separado. O backend faz spawn do serviço Node.js automaticamente. Você só precisa reiniciar `whatsflow-backend`.

### `git pull` falha por conflito em `whatsflow.db` ou `.wwebjs_auth/`
Rode `sudo bash update.sh` — ele resolve isso automaticamente.

Se persistir:
```bash
cd ~/WhatsFlow
sudo bash unblock-git.sh
```

### `403 Forbidden` no login do painel.fun
Está resolvido com `curl_cffi`. Se voltar a aparecer:
```bash
cd ~/WhatsFlow/backend
./.venv/bin/pip install --upgrade "curl_cffi>=0.7.4"
sudo systemctl restart whatsflow-backend
```

### Ver o que está rolando
```bash
# Status geral
sudo systemctl status whatsflow-backend

# Logs em tempo real
sudo journalctl -u whatsflow-backend -f

# Últimas 100 linhas
sudo journalctl -u whatsflow-backend -n 100
```

---

## 📋 Fluxo recomendado

- **Dia-a-dia**: use `sudo bash update.sh` (é seguro)
- **Uma vez por semana**: rode `sudo bash setup-auto-update.sh` e esqueça — atualiza sozinho todo dia às 04:30
- **Problema chato**: rode `sudo bash reinstall.sh`
- **Migração para servidor novo/limpo**: use Docker Compose
