"""Rotas de Webhook â recebe eventos do Evolution API."""

import logging
from fastapi import APIRouter, Request
from app.services.message_handler import process_message_webhook, process_connection_update

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@router.post("/evolution")
async def evolution_webhook(request: Request):
    """Endpoint principal que recebe TODOS os webhooks do Evolution API.

    Eventos tratados:
    - MESSAGES_UPSERT: nova mensagem enviada/recebida
    - MESSAGES_UPDATE: atualizaÃ§Ã£o de status (lido, entregue)
    - CONNECTION_UPDATE: mudanÃ§a de estado da conexÃ£o
    - QRCODE_UPDATED: novo QR Code gerado
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "detail": "Invalid JSON"}

    event = payload.get("event", "")
    instance = payload.get("instance", "unknown")

    logger.info(f"Webhook recebido: {event} | instÃ¢ncia: {instance}")

    if event == "messages.upsert":
        msg_id = await process_message_webhook(payload)
        return {"status": "ok", "message_id": msg_id}

    elif event == "connection.update":
        await process_connection_update(payload)
        return {"status": "ok", "event": "connection_update"}

    elif event == "qrcode.updated":
        # QR Code atualizado â o frontend busca via polling
        logger.info(f"QR Code atualizado para {instance}")
        return {"status": "ok", "event": "qrcode_updated"}

    elif event == "messages.update":
        # Status da mensagem (delivered, read, etc)
        logger.debug(f"Message update: {payload.get('data', {})}")
        return {"status": "ok", "event": "messages_update"}

    else:
        logger.warning(f"Evento nÃ£o tratado: {event}")
        return {"status": "ignored", "event": event}
