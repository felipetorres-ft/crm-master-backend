"""SQLite Tri-Camada â Engine do banco de dados CRM QS.

Camada 1: Armazenamento de documentos (mensagens brutas)
Camada 2: Busca full-text (FTS5 com unicode61)
Camada 3: Relacional (contatos, clientes, conversas, categorias)
"""

import aiosqlite
import os
from contextlib import asynccontextmanager
from app.core.config import get_settings

settings = get_settings()

SCHEMA_SQL = """
-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
-- â           CAMADA 3 â RELACIONAL                     â
-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT DEFAULT '#6366f1',
    icon        TEXT DEFAULT 'ð',
    created_at  TEXT DEFAULT (datetime('now'))
);

-- Categorias padrÃ£o
INSERT OR IGNORE INTO categories (name, color, icon) VALUES
    ('Business Partner', '#f59e0b', 'ð¤'),
    ('Cliente VIP', '#8b5cf6', 'â­'),
    ('Cliente QS', '#3b82f6', 'ð¤'),
    ('Fornecedor', '#10b981', 'ð­'),
    ('Consultor', '#06b6d4', 'ð¼'),
    ('FamÃ­lia', '#ec4899', 'â¤ï¸'),
    ('Equipe', '#14b8a6', 'ð¥'),
    ('Planejamento EstratÃ©gico', '#6366f1', 'ð'),
    ('NÃ£o Classificado', '#6b7280', 'â');

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT NOT NULL UNIQUE,
    name        TEXT,
    push_name   TEXT,
    category_id INTEGER DEFAULT 9,
    crm_client_id TEXT,
    profile_pic TEXT,
    is_group    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_crm ON contacts(crm_client_id);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL,
    instance    TEXT NOT NULL DEFAULT 'crm-qs-main',
    status      TEXT DEFAULT 'active',
    last_msg_at TEXT,
    msg_count   INTEGER DEFAULT 0,
    unread      INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    UNIQUE(contact_id, instance)
);

-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
-- â           CAMADA 1 â ARMAZENAMENTO (DOCUMENTOS)     â
-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    message_id      TEXT UNIQUE,
    sender_phone    TEXT,
    sender_name     TEXT,
    content         TEXT,
    media_type      TEXT,
    media_url       TEXT,
    msg_type        TEXT DEFAULT 'text',
    direction       TEXT NOT NULL CHECK(direction IN ('sent', 'received')),
    status          TEXT DEFAULT 'delivered',
    timestamp       TEXT NOT NULL,
    raw_data        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_msgid ON messages(message_id);

-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
-- â           CAMADA 2 â BUSCA FULL-TEXT (FTS5)         â
-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    sender_name,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers para manter FTS sincronizado
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, sender_name)
    VALUES (new.id, new.content, new.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
    VALUES ('delete', old.id, old.content, old.sender_name);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, sender_name)
    VALUES ('delete', old.id, old.content, old.sender_name);
    INSERT INTO messages_fts(rowid, content, sender_name)
    VALUES (new.id, new.content, new.sender_name);
END;

-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
-- â           TABELAS AUXILIARES                        â
-- ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

CREATE TABLE IF NOT EXISTS crm_clients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    phones      TEXT,
    email       TEXT,
    category    TEXT,
    status      TEXT,
    data_json   TEXT,
    imported_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_crm_phones ON crm_clients(phones);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- WAL mode para melhor concorrÃªncia
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
"""


async def init_db():
    """Inicializa o banco de dados com o schema tri-camada."""
    os.makedirs(os.path.dirname(settings.database_path), exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


@asynccontextmanager
async def get_db():
    """Context manager para conexÃ£o com o banco."""
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
