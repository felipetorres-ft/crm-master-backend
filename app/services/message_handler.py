"""ServiÃ§o de processamento de mensagens.

Recebe webhooks do Evolution, classifica, armazena no SQLite tri-camada,
e faz matching automÃ¡tico com clientes do CRM.
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional, Tuple
from app.core.database import get_db
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_phone(phone: str) -> str:
    """Normaliza telefone: remove caracteres, strip +55 se necessÃ¡rio."""
    digits = re.sub(r"\D", "", phone)
    # Remover @s.whatsapp.net ou @g.us
    digits = digits.split("@")[0]
    # Strip country code 55 se > 11 dÃ­gitos
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits


def classify_message_type(msg_data: dict) -> str:
    """Classifica o tipo de mensagem baseado no payload do Evolution."""
    msg = msg_data.get("message", {})
    if not msg:
        return "text"

    if "imageMessage" in msg:
        return "image"
    elif "videoMessage" in msg:
        return "video"
    elif "audioMessage" in msg:
        return "audio"
    elif "documentMessage" in msg:
        return "document"
    elif "stickerMessage" in msg:
        return "sticker"
    elif "contactMessage" in msg:
        return "contact"
    elif "locationMessage" in msg:
        return "location"
    elif "reactionMessage" in msg:
        return "reaction"
    elif "protocolMessage" in msg:
        return "protocol"
    elif "extendedTextMessage" in msg:
        return "text"
    elif "conversation" in msg:
        return "text"
    return "unknown"


def extract_content(msg_data: dict) -> str:
    """Extrai o conteÃºdo textual da mensagem."""
    msg = msg_data.get("message", {})
    if not msg:
        return ""

    # Texto direto
    if "conversation" in msg:
        return msg["conversation"]
    if "extendedTextMessage" in msg:
        return msg["extendedTextMessage"].get("text", "")

    # Legendas de mÃ­dia
    for key in ["imageMessage", "videoMessage", "documentMessage"]:
        if key in msg and "caption" in msg[key]:
            return msg[key]["caption"]

    # Tipos especiais
    if "contactMessage" in msg:
        return f"ð Contato: {msg['contactMessage'].get('displayName', '')}"
    if "locationMessage" in msg:
        lat = msg["locationMessage"].get("degreesLatitude", "")
        lng = msg["locationMessage"].get("degreesLongitude", "")
        return f"ð LocalizaÃ§Ã£o: {lat}, {lng}"
    if "reactionMessage" in msg:
        return f"ð {msg['reactionMessage'].get('text', '')}"
    if "audioMessage" in msg:
        return "ð¤ Mensagem de voz"
    if "stickerMessage" in msg:
        return "ð·ï¸ Sticker"

    return ""


def determine_direction(msg_data: dict) -> str:
    """Determina se a mensagem foi enviada ou recebida."""
    key = msg_data.get("key", {})
    if key.get("fromMe", False):
        return "sent"
    return "received"


async def get_or_create_contact(phone: str, name: Optional[str] = None, push_name: Optional[str] = None) -> int:
    """Busca ou cria um contato no banco. Retorna o ID."""
    phone_norm = normalize_phone(phone)

    async with get_db() as db:
        # Buscar existente
        cursor = await db.execute(
            "SELECT id, name FROM contacts WHERE phone = ?", (phone_norm,)
        )
        row = await cursor.fetchone()

        if row:
            # Atualizar nome se veio novo
            if name and not row["name"]:
                await db.execute(
                    "UPDATE contacts SET name = ?, updated_at = datetime('now') WHERE id = ?",
                    (name, row["id"])
                )
                await db.commit()
            return row["id"]

        # Criar novo contato
        display_name = name or push_name or phone_norm
        cursor = await db.execute(
            "INSERT INTO contacts (phone, name, push_name) VALUES (?, ?, ?)",
            (phone_norm, display_name, push_name)
        )
        await db.commit()
        contact_id = cursor.lastrowid

        # Tentar matching automÃ¡tico com CRM
        await try_match_crm_client(db, contact_id, phone_norm)

        logger.info(f"Novo contato criado: {display_name} ({phone_norm}) id={contact_id}")
        return contact_id


async def try_match_crm_client(db, contact_id: int, phone: str):
    """Tenta fazer matching automÃ¡tico entre contato WhatsApp e cliente CRM."""
    # Buscar nos telefones dos clientes CRM
    cursor = await db.execute(
        "SELECT id, name FROM crm_clients WHERE phones LIKE ?",
        (f"%{phone}%",)
    )
    row = await cursor.fetchone()

    if row:
        await db.execute(
            "UPDATE contacts SET crm_client_id = ?, name = COALESCE(name, ?), updated_at = datetime('now') WHERE id = ?",
            (row["id"], row["name"], contact_id)
        )
        await db.commit()
        logger.info(f"Match automÃ¡tico: contato {contact_id} â cliente CRM '{row['name']}' (id={row['id']})")


async def get_or_create_conversation(contact_id: int, instance: str = "crm-qs-main") -> int:
    """Busca ou cria uma conversa. Retorna o ID."""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM conversations WHERE contact_id = ? AND instance = ?",
            (contact_id, instance)
        )
        row = await cursor.fetchone()

        if row:
            return row["id"]

        cursor = await db.execute(
            "INSERT INTO conversations (contact_id, instance) VALUES (?, ?)",
            (contact_id, instance)
        )
        await db.commit()
        return cursor.lastrowid


async def process_message_webhook(payload: dict) -> Optional[int]:
    """Processa um webhook de mensagem do Evolution API.

    Fluxo completo:
    1. Extrai dados da mensagem
    2. Cria/busca contato
    3. Cria/busca conversa
    4. Armazena mensagem (Camada 1)
    5. FTS atualizado automaticamente (Camada 2 - trigger)
    6. Atualiza contadores da conversa (Camada 3)

    Returns: ID da mensagem inserida, ou None se duplicada/erro.
    """
    data = payload.get("data", {})
    if not data:
        return None

    key = data.get("key", {})
    remote_jid = key.get("remoteJid", "")
    message_id = key.get("id", "")
    instance = payload.get("instance", settings.evolution_instance_name)

    # Ignorar grupos por enquanto
    if remote_jid.endswith("@g.us"):
        return None

    # Ignorar mensagens do sistema
    if remote_jid == "status@broadcast":
        return None

    # Extrair phone do JID
    phone = remote_jid.split("@")[0]
    direction = determine_direction(data)
    msg_type = classify_message_type(data)
    content = extract_content(data)

    # Push name do remetente
    push_name = data.get("pushName")
    sender_name = settings.owner_name if direction == "sent" else (push_name or phone)

    # Timestamp
    ts_epoch = data.get("messageTimestamp")
    if ts_epoch:
        try:
            ts = datetime.fromtimestamp(int(ts_epoch)).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Contato
    contact_id = await get_or_create_contact(phone, name=push_name, push_name=push_name)

    # 2. Conversa
    conv_id = await get_or_create_conversation(contact_id, instance)

    # 3. Armazenar mensagem (Camada 1) â dedup por message_id
    async with get_db() as db:
        try:
            cursor = await db.execute(
                """INSERT INTO messages
                   (conversation_id, message_id, sender_phone, sender_name, content,
                    msg_type, direction, status, timestamp, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id, message_id, phone, sender_name, content,
                 msg_type, direction, "delivered", ts,
                 json.dumps(data, ensure_ascii=False, default=str))
            )
            msg_id = cursor.lastrowid

            # 4. Atualizar contadores da conversa (Camada 3)
            unread_inc = 1 if direction == "received" else 0
            await db.execute(
                """UPDATE conversations SET
                   msg_count = msg_count + 1,
                   last_msg_at = ?,
                   unread = unread + ?
                   WHERE id = ?""",
                (ts, unread_inc, conv_id)
            )

            await db.commit()
            logger.info(f"Msg #{msg_id} salva: {direction} | {msg_type} | {phone} | {content[:50]}...")
            return msg_id

        except Exception as e:
            if "UNIQUE constraint" in str(e):
                logger.debug(f"Mensagem duplicada ignorada: {message_id}")
                return None
            logger.error(f"Erro ao salvar mensagem: {e}")
            raise


async def process_connection_update(payload: dict):
    """Processa atualizaÃ§Ã£o de conexÃ£o do Evolution."""
    data = payload.get("data", {})
    state = data.get("state", "unknown")
    instance = payload.get("instance", "unknown")

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sync_log (event_type, detail) VALUES (?, ?)",
            ("connection_update", json.dumps({"instance": instance, "state": state}))
        )
        await db.commit()

    logger.info(f"ConexÃ£o atualizada: {instance} â {state}")
