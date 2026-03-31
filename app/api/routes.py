"""Rotas da API REST â serve dados para o Frontend CRM."""

import json
import logging
from fastapi import APIRouter, Query, HTTPException
from app.core.database import get_db
from app.services import evolution
from app.services.message_handler import normalize_phone
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api", tags=["api"])


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  HEALTH CHECK
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/health")
async def health():
    return {"status": "ok", "service": "CRM QS Backend", "version": settings.app_version}


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  INSTANCE / EVOLUTION
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.post("/instance/create")
async def create_instance():
    """Cria instÃ¢ncia Evolution e retorna QR Code."""
    try:
        result = await evolution.create_instance()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instance/status")
async def instance_status():
    """Status da conexÃ£o WhatsApp."""
    try:
        return await evolution.get_instance_status()
    except Exception as e:
        return {"state": "error", "detail": str(e)}


@router.get("/instance/qrcode")
async def get_qrcode():
    """ObtÃ©m QR Code para pareamento."""
    try:
        qr = await evolution.get_qrcode()
        if qr:
            return {"qrcode": qr}
        return {"qrcode": None, "detail": "JÃ¡ conectado ou aguardando"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/instance/disconnect")
async def disconnect():
    """Desconecta a instÃ¢ncia."""
    return await evolution.disconnect_instance()


@router.post("/instance/restart")
async def restart():
    """Reinicia a instÃ¢ncia."""
    return await evolution.restart_instance()


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  CONTACTS
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/contacts")
async def list_contacts(
    category: int = None,
    search: str = None,
    limit: int = Query(default=50, le=500),
    offset: int = 0
):
    """Lista contatos com filtros opcionais."""
    async with get_db() as db:
        where = ["1=1"]
        params = []

        if category:
            where.append("c.category_id = ?")
            params.append(category)

        if search:
            where.append("(c.name LIKE ? OR c.phone LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        query = f"""
            SELECT c.*, cat.name as category_name, cat.icon as category_icon,
                   COALESCE(conv.msg_count, 0) as msg_count,
                   conv.last_msg_at
            FROM contacts c
            LEFT JOIN categories cat ON c.category_id = cat.id
            LEFT JOIN conversations conv ON conv.contact_id = c.id
            WHERE {' AND '.join(where)}
            ORDER BY conv.last_msg_at DESC NULLS LAST
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        # Count total
        count_q = f"SELECT COUNT(*) FROM contacts c WHERE {' AND '.join(where)}"
        count_cursor = await db.execute(count_q, params[:-2])
        total = (await count_cursor.fetchone())[0]

        return {
            "contacts": [dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset
        }


@router.get("/contacts/{phone}/chat")
async def get_chat_history(
    phone: str,
    month: str = None,
    search: str = None,
    limit: int = Query(default=500, le=5000),
    offset: int = 0
):
    """HistÃ³rico de chat de um contato â usado pelo frontend CRM."""
    phone_norm = normalize_phone(phone)

    async with get_db() as db:
        # Buscar contato
        cursor = await db.execute(
            """SELECT c.*, cat.name as category_name
               FROM contacts c
               LEFT JOIN categories cat ON c.category_id = cat.id
               WHERE c.phone = ?""",
            (phone_norm,)
        )
        contact = await cursor.fetchone()
        if not contact:
            raise HTTPException(status_code=404, detail="Contato nÃ£o encontrado")

        # Buscar conversa
        cursor = await db.execute(
            "SELECT id FROM conversations WHERE contact_id = ?",
            (contact["id"],)
        )
        conv = await cursor.fetchone()
        if not conv:
            return {"contact": dict(contact), "messages": [], "total": 0, "months": {}}

        # Filtros
        where = ["m.conversation_id = ?"]
        params = [conv["id"]]

        if month:
            where.append("strftime('%Y-%m', m.timestamp) = ?")
            params.append(month)

        if search:
            # Usar FTS5 (Camada 2)
            where.append("m.id IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?)")
            params.append(search)

        # Mensagens
        query = f"""
            SELECT m.id, m.sender_name, m.content, m.msg_type, m.direction,
                   m.status, m.timestamp, m.media_url
            FROM messages m
            WHERE {' AND '.join(where)}
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await db.execute(query, params)
        messages = [dict(r) for r in await cursor.fetchall()]

        # Count total
        count_q = f"SELECT COUNT(*) FROM messages m WHERE {' AND '.join(where)}"
        count_cursor = await db.execute(count_q, params[:-2])
        total = (await count_cursor.fetchone())[0]

        # Meses disponÃ­veis
        cursor = await db.execute(
            """SELECT strftime('%Y-%m', timestamp) as ym, COUNT(*) as cnt
               FROM messages WHERE conversation_id = ?
               GROUP BY ym ORDER BY ym DESC""",
            (conv["id"],)
        )
        months = {r["ym"]: r["cnt"] for r in await cursor.fetchall()}

        return {
            "contact": dict(contact),
            "messages": messages,
            "total": total,
            "months": months
        }


@router.patch("/contacts/{phone}")
async def update_contact(phone: str, data: dict):
    """Atualiza dados de um contato (categoria, nome, link CRM)."""
    phone_norm = normalize_phone(phone)

    async with get_db() as db:
        sets = []
        params = []
        for key in ["name", "category_id", "crm_client_id"]:
            if key in data:
                sets.append(f"{key} = ?")
                params.append(data[key])

        if not sets:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        sets.append("updated_at = datetime('now')")
        params.append(phone_norm)

        await db.execute(
            f"UPDATE contacts SET {', '.join(sets)} WHERE phone = ?",
            params
        )
        await db.commit()
        return {"status": "ok", "phone": phone_norm}


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  MESSAGES â ENVIO
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.post("/messages/send")
async def send_message(data: dict):
    """Envia mensagem de texto via WhatsApp."""
    phone = data.get("phone")
    text = data.get("text")
    if not phone or not text:
        raise HTTPException(status_code=400, detail="phone e text sÃ£o obrigatÃ³rios")

    result = await evolution.send_text_message(phone, text)
    return {"status": "ok", "result": result}


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  SEARCH â FTS5 (CAMADA 2)
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/search")
async def search_messages(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=50, le=200)
):
    """Busca full-text nas mensagens usando FTS5."""
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT m.id, m.content, m.sender_name, m.timestamp, m.direction,
                      c.name as contact_name, c.phone as contact_phone,
                      rank
               FROM messages_fts
               JOIN messages m ON m.id = messages_fts.rowid
               JOIN conversations conv ON m.conversation_id = conv.id
               JOIN contacts c ON conv.contact_id = c.id
               WHERE messages_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (q, limit)
        )
        results = [dict(r) for r in await cursor.fetchall()]
        return {"results": results, "total": len(results), "query": q}


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  DASHBOARD / STATS
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/dashboard")
async def dashboard_stats():
    """EstatÃ­sticas gerais do CRM WhatsApp."""
    async with get_db() as db:
        stats = {}

        cursor = await db.execute("SELECT COUNT(*) FROM contacts")
        stats["total_contacts"] = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        stats["total_messages"] = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE direction='sent'")
        stats["total_sent"] = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM messages WHERE direction='received'")
        stats["total_received"] = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM conversations WHERE status='active'")
        stats["active_conversations"] = (await cursor.fetchone())[0]

        # Por categoria
        cursor = await db.execute(
            """SELECT cat.name, cat.icon, COUNT(c.id) as cnt
               FROM categories cat
               LEFT JOIN contacts c ON c.category_id = cat.id
               GROUP BY cat.id ORDER BY cnt DESC"""
        )
        stats["categories"] = {f"{r['icon']} {r['name']}": r["cnt"] for r in await cursor.fetchall()}

        # Mensagens por mÃªs
        cursor = await db.execute(
            """SELECT strftime('%Y-%m', timestamp) as ym, COUNT(*) as cnt
               FROM messages GROUP BY ym ORDER BY ym DESC LIMIT 12"""
        )
        stats["messages_per_month"] = {r["ym"]: r["cnt"] for r in await cursor.fetchall()}

        return stats


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  CATEGORIES
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.get("/categories")
async def list_categories():
    """Lista todas as categorias."""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM categories ORDER BY name")
        return {"categories": [dict(r) for r in await cursor.fetchall()]}


# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
#  SYNC / IMPORT
# ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@router.post("/sync/crm-clients")
async def import_crm_clients(data: dict):
    """Importa clientes do CRM (JSON) para matching com contatos WhatsApp."""
    clients = data.get("clients", [])
    if not clients:
        raise HTTPException(status_code=400, detail="Lista de clientes vazia")

    imported = 0
    matched = 0

    async with get_db() as db:
        for client in clients:
            client_id = client.get("id", "")
            name = client.get("name", "")
            phones = client.get("phones", "")
            email = client.get("email", "")
            category = client.get("category", "")

            try:
                await db.execute(
                    """INSERT OR REPLACE INTO crm_clients
                       (id, name, phones, email, category, data_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (client_id, name, phones, email, category,
                     json.dumps(client, ensure_ascii=False))
                )
                imported += 1

                # Tentar match com contatos existentes
                if phones:
                    for p in phones.split(";"):
                        p_norm = normalize_phone(p.strip())
                        if len(p_norm) >= 10:
                            cursor = await db.execute(
                                "SELECT id FROM contacts WHERE phone = ?", (p_norm,)
                            )
                            row = await cursor.fetchone()
                            if row:
                                await db.execute(
                                    "UPDATE contacts SET crm_client_id = ?, name = COALESCE(name, ?) WHERE id = ?",
                                    (client_id, name, row["id"])
                                )
                                matched += 1

            except Exception as e:
                logger.error(f"Erro importando cliente {name}: {e}")

        await db.commit()

    return {"status": "ok", "imported": imported, "matched": matched}
