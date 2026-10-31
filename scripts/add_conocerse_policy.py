"""Add the "conocerse" doctrine to the VIP persona catalog (one-off).

The VIP catalog had no policy about a VIP asking to meet in person. The only
similar rule ("no existe el contacto personal ni las citas") lives in the
ATENCION catalog, so every "¿cuándo nos conocemos?" landed in the gray zone.

Panel policies are matched deterministically by tema (``signals ∩ temas``), and
the Analyst already emits ``conexion`` / ``reencuentro`` for these turns, so
tagging the rule with them makes it findable without relying on embeddings.

Idempotent: re-running with the policy already present leaves the catalog
untouched. Writes a NEW persona version through the same service the owner's
panel uses (validate → insert → activate).

Usage:
    python scripts/add_conocerse_policy.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from diana.application.persona_admin_service import PersonaAdminService
from diana.cognitive.persona_catalog import validate_persona_catalog
from diana.config.settings import Settings
from diana.infrastructure.db.repositories.persona_versions import PersonaVersionRepo
from diana.infrastructure.db.session import create_session_factory

POLICY_ID = "conocerse_sin_confirmar"
POLICY = {
    "id": POLICY_ID,
    # Un solo tema, específico: el Analista lo emite para pedidos de conocerse /
    # vernos / encuentro / cita (ver analyst._SYSTEM). Temas generales como
    # "conexion" harían que la regla se activara en turnos que necesitan otra
    # doctrina y el Decisor dejaría de consultar.
    "tema": ["conocerse"],
    "regla": (
        "Si un VIP pregunta cuándo o cómo podrían conocerse en persona, propone "
        "un encuentro o insiste con una cita: no negarlo por completo ni "
        "confirmarlo nunca — tratarlo como un 'tal vez'. Responder con calidez, "
        "sin prometer fecha, lugar ni compromiso, y redirigir la charla a algo "
        "cotidiano."
    ),
}


async def main(dry_run: bool) -> int:
    settings = Settings()
    repo = PersonaVersionRepo(create_session_factory())
    active = await repo.get_active(channel_type="vip")
    if active is None:
        print("No active VIP persona version; nothing to do.")
        return 1

    payload = dict(active.payload)
    policies = list(payload.get("policies") or [])
    existing = next((p for p in policies if p.get("id") == POLICY_ID), None)
    if existing == POLICY:
        print(f"Policy {POLICY_ID!r} already up to date in version {active.version}.")
        return 0

    payload["policies"] = (
        [POLICY if p.get("id") == POLICY_ID else p for p in policies]
        if existing is not None
        else policies + [POLICY]
    )
    validate_persona_catalog(payload)
    action = "Update" if existing is not None else "Add"
    print(f"Active VIP version {active.version}: {len(policies)} policies.")
    print(f"{action}: {POLICY_ID} (temas: {', '.join(POLICY['tema'])})")
    if dry_run:
        print("Dry run: no version written.")
        return 0

    service = PersonaAdminService(
        payload_store=repo,
        feature_persona_admin_enabled=True,
        owner_telegram_id=settings.owner_telegram_id,
    )
    record = await service.save_persona(
        settings.owner_telegram_id, payload, channel_type="vip"
    )
    print(f"Activated VIP persona version {record.version} ({record.id}).")
    # The running bot caches the catalog in memory (PersonaCatalogProvider).
    # Writing from this process does not invalidate that cache.
    print(
        "IMPORTANT: restart the bot for the running process to load this "
        "version: systemctl --user restart diana-bot"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.dry_run)))
