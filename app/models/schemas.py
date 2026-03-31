"""Pydantic schemas para validaÃ§Ã£o de dados."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ââ Contacts ââ

class ContactBase(BaseModel):
    phone: str
    name: Optional[str] = None
    push_name: Optional[str] = None
    category_id: Optional[int] = 9
    crm_client_id: Optional[str] = None

class ContactOut(ContactBase):
    id: int
    profile_pic: Optional[str] = None
    is_group: bool = False
    created_at: str
    updated_at: str
    msg_count: Optional[int] = 0
    last_msg_at: Optional[str] = None

class ContactUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    crm_client_id: Optional[str] = None


# ââ Messages ââ

class MessageOut(BaseModel):
    id: int
    sender_name: Optional[str] = None
    content: Optional[str] = None
    msg_type: str = "text"
    direction: str
    status: str = "delivered"
    timestamp: str
    media_url: Optional[str] = None

class ChatHistory(BaseModel):
    contact: ContactOut
    messages: List[MessageOut]
    total: int
    months: dict


# ââ Evolution Webhook ââ

class EvolutionWebhookPayload(BaseModel):
    event: Optional[str] = None
    instance: Optional[str] = None
    data: Optional[dict] = None
    apikey: Optional[str] = None


# ââ Instance ââ

class InstanceStatus(BaseModel):
    instance_name: str
    status: str
    phone: Optional[str] = None
    qrcode: Optional[str] = None
    profile_pic: Optional[str] = None


# ââ Search ââ

class SearchResult(BaseModel):
    message_id: int
    content: str
    sender_name: Optional[str] = None
    timestamp: str
    contact_name: Optional[str] = None
    contact_phone: str
    rank: Optional[float] = None


# ââ Dashboard ââ

class DashboardStats(BaseModel):
    total_contacts: int = 0
    total_messages: int = 0
    total_sent: int = 0
    total_received: int = 0
    active_conversations: int = 0
    categories: dict = {}
    messages_per_month: dict = {}
