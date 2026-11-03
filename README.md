# 📱 WhatsFlow

Sistema WhatsApp automatizado para revenda de IPTV / P2P / Hybrid.
Roda numa **Raspberry Pi** conectando WhatsApp via `whatsapp-web.js` e integrando
com o painel.fun (api.controle.fit) para criar testes e renovações.
Pagamentos via **InfinitePay**.

## ✨ Recursos

- 💬 **WhatsApp Web** — QR code, envio/recebimento e mídia (imagens)
- 🤖 **Bot de comandos** — cliente OU admin envia `/teste iptv MAC` e o sistema cria automático
- 🎯 **Templates editáveis** com prévia estilo WhatsApp + upload de imagem
- ⏰ **Notificações automáticas** — 7/3/1/0 dias antes + 1/3/7 dias após vencimento
- 🔁 **Reminders pós-teste** — mensagens automáticas 1h e 3h após criar um teste
- 💳 **Renovação com InfinitePay** — link único por cliente `/pay/{customer_id}`
- 🌐 **Página pública `/teste`** — cliente pede seu próprio teste sem falar com você
- 🔐 **Login admin** com senha (JWT + rate-limit)
- 💾 **SQLite local** — banco leve, perfeito pra Raspberry

## 🍓 Instalação na Raspberry Pi

Raspberry Pi 4 (4GB+) com Raspberry Pi OS 64-bit é o recomendado.

### Comando rápido (uma linha só)

```bash
cd ~ && \
git clone https://github.com/rithielezeft/fivezap.git WhatsFlow && \
cd WhatsFlow && \
sudo bash install.sh
```

Isso instala tudo: Python, Node, Chromium, Nginx, systemd services e sobe o app.

Pronto! Acesse `http://<ip-da-raspberry>/login`.

### Com domínio próprio + HTTPS

Se você tem um domínio apontado pro IP da Raspberry (via DNS ou Cloudflare Tunnel):

```bash
cd ~/WhatsFlow
sudo DOMAIN=whatsflow.seudominio.com bash install.sh
```

O instalador emite certificado Let's Encrypt automaticamente.

### Trocar a senha admin no primeiro acesso

Depois de entrar, vá em **Configurações** → botão "Trocar senha".
Ou defina antes de instalar:

```bash
sudo ADMIN_PW="MinhaSenhaForte" bash install.sh
```

## 🚀 Primeiros passos

1. Login com a senha padrão `Rithi0518@`
2. **WhatsApp** → escaneie o QR code (a sessão fica salva)
3. **Configurações** → preencha:
   - **InfiniteTag** (handle da sua conta InfinitePay)
   - Preços por plano (R$ 35,00 etc.)
4. **Notificações** → personalize as 11 mensagens automáticas com sua marca e imagens
5. **Comandos** → cadastre `/teste p2p`, `/teste iptv MAC` etc.
6. **Clientes** → clique "Atualizar do painel" pra puxar todos os seus usuários do painel.fun

## 📂 Estrutura

```
WhatsFlow/
├── backend/                 # FastAPI + SQLite (Python)
│   ├── server.py            # App principal
│   ├── database.py          # Schema + seed
│   ├── models.py            # Pydantic
│   ├── routers/             # Endpoints REST
│   ├── services/            # Painel.fun, InfinitePay, bot, scheduler
│   ├── uploads/             # Imagens dos templates
│   ├── whatsflow.db         # ⚠️ Não commitar — banco local
│   └── requirements.txt
├── whatsapp-service/        # whatsapp-web.js (Node.js)
│   ├── index.js
│   ├── .wwebjs_auth/        # ⚠️ Não commitar — sessão WhatsApp
│   └── package.json
├── frontend/                # React + Tailwind + Shadcn
│   ├── src/
│   │   ├── pages/           # Dashboard, Clientes, Testes, Notificações, etc.
│   │   └── components/
│   └── package.json
├── install.sh               # Instalador automático Raspberry
├── DEPLOY_RASPBERRY.md      # Guia detalhado passo-a-passo
└── README.md
```

## 🛠 Comandos úteis

```bash
# Logs
sudo journalctl -u whatsflow-backend -f
tail -f /var/log/whatsapp-service.out.log

# Restart
sudo systemctl restart whatsflow-backend nginx

# Backup do banco (roda automático via cron.daily)
sudo cp backend/whatsflow.db ~/backups/whatsflow-$(date +%F).db

# Atualizar
cd ~/WhatsFlow && git pull && \
  cd backend && .venv/bin/pip install -r requirements.txt && cd .. && \
  cd whatsapp-service && yarn install && cd .. && \
  cd frontend && yarn install && yarn build && cd .. && \
  sudo systemctl restart whatsflow-backend
```

## 🔗 API principais

| Método | Rota                                  | Descrição                                     |
|--------|---------------------------------------|-----------------------------------------------|
| POST   | `/api/auth/login`                     | Login admin com senha                         |
| GET    | `/api/dashboard/stats`                | Métricas gerais                               |
| GET    | `/api/painel/users`                   | Lista clientes do painel.fun (cacheado)       |
| POST   | `/api/painel/users/refresh`           | Força atualização do cache                    |
| POST   | `/api/painel/renew`                   | Renova cliente do painel                      |
| POST   | `/api/trials`                         | Cria teste (via admin)                        |
| GET/PUT| `/api/notifications`                  | CRUD dos templates                            |
| POST   | `/api/uploads`                        | Upload de imagem para template                |
| GET    | `/api/reminders`                      | Lista agendamentos pendentes                  |
| POST   | `/api/public/trial`                   | Público — página `/teste`                     |
| GET    | `/api/pay/customer/{id}`              | Público — dados p/ página `/pay/{id}`         |
| POST   | `/api/payments/webhook`               | Callback do InfinitePay                       |

## 📖 Documentação detalhada

Veja **[DEPLOY_RASPBERRY.md](./DEPLOY_RASPBERRY.md)** para instalação manual passo-a-passo.

## 📝 Licença

Uso pessoal / comercial de acordo com o dono do repositório.
