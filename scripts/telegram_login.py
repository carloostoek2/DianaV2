"""Inicio de sesión de Telethon para la cuenta personal (script de operación).

La sesión de Telethon es la llave con la que el bot lee el historial del chat
personal con cada VIP. Este script la crea o la repara en pasos separados,
porque el código llega por Telegram y hay que esperarlo:

    python scripts/telegram_login.py --status
    python scripts/telegram_login.py --phone +521234567890
    python scripts/telegram_login.py --code 12345
    python scripts/telegram_login.py --password <clave de dos pasos>

El paso --phone envía el código y guarda el identificador de esa solicitud;
los pasos siguientes lo reutilizan. La sesión se escribe en la ruta indicada
por TELETHON_SESSION_PATH (sin el sufijo .session).

Ejecutar desde la raíz del repositorio con el intérprete del proyecto:

    .venv/bin/python scripts/telegram_login.py --status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

# Settings() lee .env con ruta relativa: el script fija la raíz del proyecto.
os.chdir(_ROOT)

from diana.config.settings import Settings  # noqa: E402

_STATE_PATH = _ROOT / "runtime" / "telegram_login_state.json"


def _session_name(settings: Settings) -> str:
    raw = (settings.telethon_session_path or "").strip()
    if not raw:
        raise SystemExit("TELETHON_SESSION_PATH no está configurado en .env")
    path = Path(raw)
    if path.suffix == ".session":
        path = path.with_suffix("")
    return str(path)


def _client(settings: Settings) -> object:
    from telethon import TelegramClient

    api_id = settings.telethon_api_id
    api_hash = settings.telethon_api_hash.get_secret_value().strip()
    if not api_id or not api_hash:
        raise SystemExit("TELETHON_API_ID o TELETHON_API_HASH no están configurados")
    return TelegramClient(_session_name(settings), int(api_id), api_hash)


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


async def _run_status(settings: Settings) -> int:
    client = _client(settings)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print(f"SESION_NO_AUTORIZADA ruta={_session_name(settings)}.session")
            return 1
        me = await client.get_me()
        username = f"@{me.username}" if getattr(me, "username", None) else "sin usuario"
        nombre = getattr(me, "first_name", None) or ""
        print(f"SESION_AUTORIZADA id={me.id} nombre={nombre} {username}")
        return 0
    finally:
        await client.disconnect()


async def _run_phone(settings: Settings, phone: str) -> int:
    client = _client(settings)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"YA_AUTORIZADA id={me.id} — no se envía código")
            return 1
        sent = await client.send_code_request(phone)
        state = _load_state()
        state["phone"] = phone
        state["phone_code_hash"] = sent.phone_code_hash
        _save_state(state)
        print("CODIGO_ENVIADO revisa Telegram (llega como mensaje del servicio)")
        return 0
    finally:
        await client.disconnect()


async def _run_code(settings: Settings, code: str) -> int:
    from telethon.errors import SessionPasswordNeededError

    state = _load_state()
    phone = state.get("phone")
    code_hash = state.get("phone_code_hash")
    if not phone or not code_hash:
        raise SystemExit("No hay solicitud de código guardada: ejecuta primero --phone")

    client = _client(settings)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        except SessionPasswordNeededError:
            print("REQUIERE_CLAVE_DE_DOS_PASOS ejecuta ahora --password")
            return 2
        me = await client.get_me()
        print(f"SESION_INICIADA id={me.id}")
        return 0
    finally:
        await client.disconnect()


async def _run_password(settings: Settings, password: str) -> int:
    client = _client(settings)
    await client.connect()
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        print(f"SESION_INICIADA id={me.id}")
        return 0
    finally:
        await client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicio de sesión de Telethon")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="Informa si la sesión está autorizada")
    group.add_argument("--phone", help="Número de la cuenta personal (envía el código)")
    group.add_argument("--code", help="Código recibido en Telegram")
    group.add_argument("--password", help="Clave de verificación en dos pasos")
    args = parser.parse_args()

    settings = Settings()
    if args.status:
        return asyncio.run(_run_status(settings))
    if args.phone:
        return asyncio.run(_run_phone(settings, args.phone.strip()))
    if args.code:
        return asyncio.run(_run_code(settings, args.code.strip()))
    return asyncio.run(_run_password(settings, args.password))


if __name__ == "__main__":
    raise SystemExit(main())
