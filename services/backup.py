from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, insert, select

from config import settings
from database.models import Base
from database.session import SessionFactory


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.backup_secret.encode()).digest())
    return Fernet(key)


def _json_value(value):
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    return value


def _decode_value(value):
    if isinstance(value, dict) and "__datetime__" in value:
        return datetime.fromisoformat(value["__datetime__"])
    if isinstance(value, dict) and "__date__" in value:
        return date.fromisoformat(value["__date__"])
    return value


async def create_backup() -> bytes:
    payload = {"format": 1, "created_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    async with SessionFactory() as session:
        for table in Base.metadata.sorted_tables:
            rows = (await session.execute(select(table))).mappings().all()
            payload["tables"][table.name] = [{key: _json_value(value) for key, value in row.items()} for row in rows]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _fernet().encrypt(raw)


async def restore_backup(blob: bytes) -> dict[str, int]:
    try:
        payload = json.loads(_fernet().decrypt(blob))
    except (InvalidToken, json.JSONDecodeError) as exc:
        raise ValueError("فایل بکاپ معتبر نیست یا کلید بکاپ اشتباه است.") from exc
    if payload.get("format") != 1:
        raise ValueError("نسخه بکاپ پشتیبانی نمی‌شود.")
    counts: dict[str, int] = {}
    async with SessionFactory.begin() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        for table in Base.metadata.sorted_tables:
            rows = payload["tables"].get(table.name, [])
            decoded = [{key: _decode_value(value) for key, value in row.items()} for row in rows]
            if decoded:
                await session.execute(insert(table), decoded)
            counts[table.name] = len(decoded)
    return counts

