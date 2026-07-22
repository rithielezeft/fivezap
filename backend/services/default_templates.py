"""Default notification templates — shared between database.init_db (seed)
and routers/notifications.restore-defaults (admin restore).

Keeping them in one place ensures the two paths never drift.
"""

DEFAULT_TEMPLATES = [
    {
        "event_key": "expiration_7d",
        "title": "Vencimento em 7 dias",
        "body": "Olá {name}! 👋\n\nSeu login *{user}* vence em *7 dias* ({expires_at}).\n\n{discount_line}Renove agora:\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "expiration_3d",
        "title": "Vencimento em 3 dias",
        "body": "Olá {name}! 👋\n\nSeu login *{user}* vence em *3 dias* ({expires_at}).\n\nRenove agora e não perca o acesso:\n{pay_link}\n\nQualquer dúvida é só chamar aqui! 😉",
        "image_url": "",
    },
    {
        "event_key": "expiration_1d",
        "title": "Vencimento amanhã",
        "body": "⚠️ Olá {name}!\n\nSeu login *{user}* vence *amanhã* ({expires_at}).\n\nRenove agora para não perder o acesso:\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "expiration_0d",
        "title": "Venceu hoje",
        "body": "🔴 Olá {name}, seu login *{user}* venceu *hoje*.\n\nRenove agora para reativar o acesso:\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "expired_1d",
        "title": "Vencido há 1 dia",
        "body": "Olá {name}, seu login *{user}* está vencido há *1 dia*. 😢\n\nQue tal renovar agora e voltar a assistir?\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "expired_3d",
        "title": "Vencido há 3 dias",
        "body": "Ei {name}, sentimos sua falta! Seu login *{user}* está vencido há *3 dias*.\n\nRenove pelo link e volte já a assistir:\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "expired_7d",
        "title": "Vencido há 7 dias",
        "body": "{name}, faz uma semana que seu login *{user}* venceu.\n\nQuer voltar? Renove agora com condição especial:\n{pay_link}",
        "image_url": "",
    },
    {
        "event_key": "renewal_success",
        "title": "Renovação confirmada",
        "body": "✅ Pagamento confirmado, {name}!\n\nSeu login *{user}* foi renovado por *{plan_months} mês(es)* e já está ativo até {new_expires_at}.\n\nObrigado pela preferência! 🎉",
        "image_url": "",
    },
]

DEFAULT_TEMPLATES_BY_EVENT = {t["event_key"]: t for t in DEFAULT_TEMPLATES}
