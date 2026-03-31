"""CRM QS Backend â FastAPI Application.

Servidor principal que integra:
- Evolution API (WhatsApp via webhook)
- SQLite tri-camada (mensagens, FTS5, relacional)
- API REST para o frontend CRM
- Painel administrativo (QR Code, instÃ¢ncias)
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.config import get_settings
from app.core.database import init_db
from app.api.routes import router as api_router
from app.api.webhook import router as webhook_router

# ââ Logging ââ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ââ Lifespan ââ
@asynccontextmanager
async def lifespan(app: FastAPI):
    """InicializaÃ§Ã£o e shutdown da aplicaÃ§Ã£o."""
    logger.info("=" * 60)
    logger.info(f"  {settings.app_name} v{settings.app_version}")
    logger.info(f"  Evolution API: {settings.evolution_api_url}")
    logger.info(f"  Database: {settings.database_path}")
    logger.info("=" * 60)

    # Inicializar banco SQLite tri-camada
    await init_db()
    logger.info("Banco de dados SQLite tri-camada inicializado")

    yield

    logger.info("Servidor encerrado")


# ââ App ââ
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

# ââ CORS ââ
origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ââ Rotas ââ
app.include_router(api_router)
app.include_router(webhook_router)

# ââ Arquivos estÃ¡ticos ââ
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ââ Frontend (SPA) ââ
templates_dir = Path(__file__).parent.parent / "templates"


@app.get("/")
async def serve_frontend():
    """Serve o frontend CRM."""
    index = templates_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "health": "/api/health",
            "dashboard": "/api/dashboard",
            "contacts": "/api/contacts",
            "search": "/api/search?q=termo",
            "instance": "/api/instance/status",
            "webhook": "/api/webhook/evolution"
        }
    }


@app.get("/admin")
async def serve_admin():
    """Serve o painel administrativo."""
    admin = templates_dir / "admin.html"
    if admin.exists():
        return FileResponse(str(admin))
    return {"detail": "Painel admin nÃ£o encontrado. Deploy pendente."}
