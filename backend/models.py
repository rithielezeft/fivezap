"""Pydantic models for WhatsFlow."""
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# ---- Customer ----
class CustomerCreate(BaseModel):
    name: str
    whatsapp: str
    system_type: str  # iptv | p2p | hybrid
    mac: Optional[str] = None
    painel_username: Optional[str] = None
    painel_password: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    whatsapp: Optional[str] = None
    system_type: Optional[str] = None
    mac: Optional[str] = None
    painel_username: Optional[str] = None
    painel_password: Optional[str] = None
    current_package_id: Optional[int] = None
    expires_at: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class Customer(BaseModel):
    id: str
    name: str
    whatsapp: str
    system_type: str
    mac: Optional[str] = None
    painel_username: Optional[str] = None
    painel_password: Optional[str] = None
    current_package_id: Optional[int] = None
    expires_at: Optional[str] = None
    status: str = "active"
    notes: Optional[str] = None
    created_at: str
    updated_at: str


# ---- Trial ----
class TrialCreate(BaseModel):
    customer_id: Optional[str] = None
    system_type: str
    mac: Optional[str] = None
    name: Optional[str] = None
    whatsapp: Optional[str] = None


class Trial(BaseModel):
    id: str
    customer_id: Optional[str] = None
    system_type: str
    mac: Optional[str] = None
    painel_user: Optional[str] = None
    painel_pass: Optional[str] = None
    trial_user_id: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str


# ---- Command Templates ----
class TemplateCreate(BaseModel):
    name: str
    trigger_command: str
    system_type: str  # iptv | p2p | hybrid
    requires_mac: bool = False
    package_id: Optional[int] = None
    response_template: Optional[str] = None
    enabled: bool = True
    trigger_source: str = "both"  # client | admin | both


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    trigger_command: Optional[str] = None
    system_type: Optional[str] = None
    requires_mac: Optional[bool] = None
    package_id: Optional[int] = None
    response_template: Optional[str] = None
    enabled: Optional[bool] = None
    trigger_source: Optional[str] = None


class Template(BaseModel):
    id: str
    name: str
    trigger_command: str
    system_type: str
    requires_mac: bool
    package_id: Optional[int] = None
    response_template: Optional[str] = None
    enabled: bool
    trigger_source: str = "both"
    created_at: str


# ---- Messages ----
class MessageIn(BaseModel):
    phone: str
    message: str
    from_me: bool = False


class Message(BaseModel):
    id: str
    customer_id: Optional[str] = None
    phone: str
    message: str
    direction: str  # in | out
    timestamp: str


# ---- Payments ----
class PaymentCreate(BaseModel):
    customer_id: str
    plan_months: int  # 1, 3, 6, 12


class Payment(BaseModel):
    id: str
    customer_id: str
    plan_months: int
    amount_cents: int
    package_id: int
    status: str
    infinitepay_url: Optional[str] = None
    order_nsu: Optional[str] = None
    paid_at: Optional[str] = None
    created_at: str


# ---- Settings ----
class SettingsUpdate(BaseModel):
    painel_username: Optional[str] = None
    painel_password: Optional[str] = None
    painel_base_url: Optional[str] = None
    twocaptcha_key: Optional[str] = None
    turnstile_sitekey: Optional[str] = None
    turnstile_pageurl: Optional[str] = None
    infinitepay_handle: Optional[str] = None
    notification_days: Optional[str] = None
    trial_package_id: Optional[str] = None
    public_base_url: Optional[str] = None
    timezone: Optional[str] = None
    plan_price_1m: Optional[str] = None
    plan_price_3m: Optional[str] = None
    plan_price_6m: Optional[str] = None
    plan_price_12m: Optional[str] = None


# ---- Public trial request ----
class PublicTrialRequest(BaseModel):
    name: str
    whatsapp: str
    system_type: str  # iptv | p2p | hybrid
    mac: Optional[str] = None


# ---- WhatsApp webhook (from Node) ----
class IncomingWhatsAppMessage(BaseModel):
    from_number: str = Field(..., alias="from")
    body: str
    from_me: bool = False
    timestamp: Optional[int] = None

    class Config:
        populate_by_name = True
