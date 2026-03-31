"""ServiÃ§o de integraÃ§Ã£o com Evolution API.

Gerencia instÃ¢ncias, QR Code, envio/recebimento de mensagens.
"""

import httpx
import logging
from typing import Optional
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = settings.evolution_api_url
API_KEY = settings.evolution_api_key
INSTANCE = settings.evolution_instance_name

HEADERS = {
    "apikey": API_KEY,
    "Content-Type": "application/json"
}


async def create_instance(instance_name: str = INSTANCE) -> dict:
    """Cria uma nova instÃ¢ncia no Evolution API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/instance/create",
            headers=HEADERS,
            json={
                "instanceName": instance_name,
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
                "rejectCall": False,
                "groupsIgnore": False,
                "alwaysOnline": False,
                "readMessages": False,
                "readStatus": False,
                "syncFullHistory": True,
                "webhook": {
                    "url": f"{settings.evolution_api_url.replace('evolution', 'backend')}/api/webhook/evolution",
                    "byEvents": True,
                    "base64": False,
                    "events": [
                        "MESSAGES_UPSERT",
                        "MESSAGES_UPDATE",
                        "CONNECTION_UPDATE",
                        "QRCODE_UPDATED"
                    ]
                }
            }
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"InstÃ¢ncia '{instance_name}' criada: {data}")
        return data


async def get_instance_status(instance_name: str = INSTANCE) -> dict:
    """ObtÃ©m o status da instÃ¢ncia (connected, disconnected, qrcode)."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{BASE_URL}/instance/connectionState/{instance_name}",
                headers=HEADERS
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"instance": instance_name, "state": "not_found"}
            raise


async def get_qrcode(instance_name: str = INSTANCE) -> Optional[str]:
    """ObtÃ©m o QR Code para pareamento (base64 image)."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{BASE_URL}/instance/connect/{instance_name}",
                headers=HEADERS
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("base64", data.get("code"))
        except Exception as e:
            logger.error(f"Erro ao obter QR Code: {e}")
            return None


async def disconnect_instance(instance_name: str = INSTANCE) -> dict:
    """Desconecta a instÃ¢ncia do WhatsApp."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{BASE_URL}/instance/logout/{instance_name}",
            headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json()


async def restart_instance(instance_name: str = INSTANCE) -> dict:
    """Reinicia a instÃ¢ncia."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{BASE_URL}/instance/restart/{instance_name}",
            headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json()


async def send_text_message(phone: str, text: str, instance_name: str = INSTANCE) -> dict:
    """Envia mensagem de texto via WhatsApp."""
    # Normalizar telefone (garantir formato 55XXXXXXXXXXX)
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    if not phone_clean.startswith("55"):
        phone_clean = "55" + phone_clean

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/message/sendText/{instance_name}",
            headers=HEADERS,
            json={
                "number": phone_clean,
                "text": text
            }
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Mensagem enviada para {phone_clean}")
        return data


async def fetch_contacts(instance_name: str = INSTANCE) -> list:
    """Busca todos os contatos da instÃ¢ncia."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/chat/findContacts/{instance_name}",
            headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_messages(phone: str, count: int = 100, instance_name: str = INSTANCE) -> list:
    """Busca mensagens de um contato especÃ­fico."""
    phone_clean = phone.replace("+", "").replace("-", "").replace(" ", "")
    if not phone_clean.startswith("55"):
        phone_clean = "55" + phone_clean

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/findMessages/{instance_name}",
            headers=HEADERS,
            json={
                "where": {
                    "key": {
                        "remoteJid": f"{phone_clean}@s.whatsapp.net"
                    }
                },
                "limit": count
            }
        )
        resp.raise_for_status()
        return resp.json()


async def list_instances() -> list:
    """Lista todas as instÃ¢ncias registradas."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/instance/fetchInstances",
            headers=HEADERS
        )
        resp.raise_for_status()
        return resp.json()
