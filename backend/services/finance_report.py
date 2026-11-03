"""Monthly finance PDF (recebido, créditos gastos, lucro, renovações) + WhatsApp delivery."""
import base64
import io
import logging
from datetime import datetime, timezone

import httpx

from database import get_setting, set_setting
from services.whatsapp_client import WA_SERVICE_URL

logger = logging.getLogger(__name__)

MONTHS = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
          "Setembro", "Outubro", "Novembro", "Dezembro"]


def _money(cents) -> str:
    v = f"{(cents or 0) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v}"


def _parse_brl(raw) -> float:
    try:
        return float(str(raw or "").replace("R$", "").strip().replace(".", "").replace(",", ".") or 0)
    except ValueError:
        return 0.0


async def credits_for(paid_rows: list) -> dict:
    """Credits spent on the month's renewals, priced with the configured cost per credit."""
    raw = await get_setting("credits_per_plan") or "1:1,3:3,6:6,12:12"
    per_plan = {}
    for part in raw.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                per_plan[int(k)] = float(v.replace(",", "."))
            except ValueError:
                pass
    used = sum(per_plan.get(int(r["plan_months"]), float(r["plan_months"])) for r in paid_rows)
    unit = _parse_brl(await get_setting("credit_unit_cost"))
    cost_cents = int(round(used * unit * 100))
    received = sum(r["amount_cents"] for r in paid_rows)
    return {
        "used": round(used, 2),
        "per_plan": per_plan,
        "unit_cost_cents": int(round(unit * 100)),
        "cost_cents": cost_cents,
        "profit_cents": received - cost_cents if unit else None,
    }


async def _balance() -> dict:
    try:
        from routers.dashboard import balances
        return (await balances()).get("painel") or {}
    except Exception:
        logger.exception("painel balance lookup failed")
        return {}


async def build_pdf(month: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from routers.finance import summary, paid_rows_for

    s = await summary(month)
    c = s["credits"]
    bal = await _balance()
    brand = (await get_setting("brand_name") or "").strip() or "WhatsFlow"
    y, m = month.split("-")
    st = getSampleStyleSheet()
    green, dark = colors.HexColor("#059669"), colors.HexColor("#0F172A")

    def table(rows, widths, header=True):
        t = Table(rows, colWidths=widths)
        style = [("FONTSIZE", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                 ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0"))]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), dark), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(style))
        return t

    kpis = [
        ["Recebido no mês", _money(s["received"]["amount_cents"]), f'{s["received"]["count"]} faturas'],
        ["Créditos gastos (renovações)", f'{c["used"]:g}', f'custo {_money(c["cost_cents"])}' if c["unit_cost_cents"] else "configure o custo por crédito"],
        ["Lucro estimado", _money(c["profit_cents"]) if c["profit_cents"] is not None else "—", "recebido − custo dos créditos"],
        ["Pendente", _money(s["pending"]["amount_cents"]), f'{s["pending"]["count"]} links'],
        ["Ticket médio", _money(s["ticket_cents"]), f'conversão {s["conversion_percent"] or 0}%'],
        ["Cupons", _money(s["coupons"]["discount_cents"]), f'{s["coupons"]["count"]} usados'],
    ]
    if bal:
        kpis.append(["Saldo atual no painel", f'{bal.get("balance", 0):g} créditos',
                     f'última recarga: {bal.get("last_recharge_credits") or 0:g} créditos'])

    story = [
        Paragraph(f'<font color="#059669"><b>{brand}</b></font> · Relatório financeiro', st["Title"]),
        Paragraph(f"{MONTHS[int(m) - 1]} de {y}", st["Heading2"]),
        Spacer(1, 0.3 * cm),
        table([["Indicador", "Valor", "Detalhe"]] + kpis, [6 * cm, 4.5 * cm, 6.5 * cm]),
        Spacer(1, 0.5 * cm),
        Paragraph("Renovações por período", st["Heading3"]),
        table([["Mensal", "Trimestral", "Semestral", "Anual"],
               [str(s["by_period"].get(k, 0)) for k in ("1", "3", "6", "12")]], [4.25 * cm] * 4),
        Spacer(1, 0.5 * cm),
        Paragraph("Top clientes", st["Heading3"]),
        table([["#", "Cliente", "Faturas", "Total"]] +
              [[str(i + 1), t["login"], str(t["count"]), _money(t["amount_cents"])] for i, t in enumerate(s["top_clients"])] or [["", "Sem dados", "", ""]],
              [1 * cm, 8 * cm, 3 * cm, 5 * cm]),
        Spacer(1, 0.5 * cm),
        Paragraph("Pagamentos confirmados", st["Heading3"]),
    ]
    rows = await paid_rows_for(month)
    story.append(table([["Data", "Cliente", "Plano", "Valor", "Comprovante"]] + [
        [r["_paid"].strftime("%d/%m %H:%M"), r["login"], f'{r["plan_months"]}m', _money(r["amount_cents"]),
         "sim" if r.get("receipt_url") else "—"] for r in rows] or [["", "Nenhum pagamento", "", "", ""]],
        [3 * cm, 6 * cm, 2 * cm, 3.5 * cm, 2.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f'<font size="7" color="#64748B">Gerado em {datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")} UTC · '
                           f'créditos calculados por plano ({", ".join(f"{k}m={v:g}" for k, v in c["per_plan"].items())})</font>', st["Normal"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm,
                      bottomMargin=1.5 * cm, title=f"Relatorio {month}").build(story)
    _ = green
    return buf.getvalue()


async def send_report(month: str, force: bool = False) -> dict:
    key = f"monthly_report_sent_{month}"
    if not force and await get_setting(key):
        return {"sent": False, "reason": "já enviado"}
    admin = (await get_setting("admin_whatsapp") or "").strip()
    if not admin:
        return {"sent": False, "reason": "WhatsApp do admin não configurado em Configurações"}
    pdf = await build_pdf(month)
    y, m = month.split("-")
    payload = {
        "phone": admin,
        "message": f"📊 *Relatório financeiro — {MONTHS[int(m) - 1]}/{y}*\nSegue o PDF com recebimentos, créditos gastos e lucro do mês.",
        "image_url": "data:application/pdf;base64," + base64.b64encode(pdf).decode(),
        "filename": f"financeiro-{month}.pdf",
        "idempotency_key": f"{key}:{int(force)}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{WA_SERVICE_URL}/send", json=payload)
    if r.status_code >= 300:
        return {"sent": False, "reason": f"WhatsApp: {r.text[:200]}"}
    await set_setting(key, datetime.now(timezone.utc).isoformat())
    return {"sent": True, "to": admin}


def previous_month(now: datetime) -> str:
    y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    return f"{y}-{m:02d}"


async def maybe_send_previous_month():
    """Idempotent: from the 1st of each month, send last month's PDF once (Raspberry hourly loop)."""
    from services.scheduler import _get_display_tz
    now = datetime.now(timezone.utc).astimezone(await _get_display_tz())
    if now.day > 3 or now.hour < 9:
        return None
    month = previous_month(now)
    if await get_setting(f"monthly_report_sent_{month}"):
        return None
    res = await send_report(month)
    logger.info("monthly report %s: %s", month, res)
    return res
