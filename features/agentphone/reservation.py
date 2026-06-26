"""High-level "call a restaurant and book a table" composer.

`book_table()` builds the agent system prompt (Russian by default) and the
POST /v1/calls payload, but DEFAULTS to dry_run=True and returns the payload
WITHOUT placing a call. A real call requires BOTH dry_run=False AND the explicit
operator flag confirm_real_call=True (and an agentId) — so tests can never dial.
"""
from __future__ import annotations

import re

from . import client

# Russian reservation script. Kept as one template so the call's persona is
# auditable before any real dial. {place}/{party}/{when}/{name} are filled in.
_RU_SYSTEM_PROMPT = (
    "Ты — вежливый русскоязычный ассистент, который звонит в ресторан «{place}», "
    "чтобы забронировать столик от имени гостя.\n"
    "Задача: забронировать стол на {party} человек(а) на {when}.\n"
    "Правила разговора:\n"
    "- Говори по-русски, естественно, коротко и дружелюбно.\n"
    "- В начале представься и сразу назови дату, время и количество гостей.\n"
    "- Если названное время недоступно — спроси ближайшее доступное и предложи его гостю.\n"
    "- Если спросят имя для брони — назови: {name}.\n"
    "- Если спросят контактный телефон — вежливо скажи, что перезвонят при необходимости.\n"
    "- В конце обязательно проговори и подтверди финальные детали брони "
    "(ресторан, дата, время, число гостей) и поблагодари.\n"
    "- Не соглашайся ни на какую предоплату и не диктуй данные банковской карты."
)

_RU_GREETING = (
    "Здравствуйте! Я звоню, чтобы забронировать столик в ресторане «{place}» "
    "на {party} человек(а) на {when}. Подскажите, пожалуйста, это возможно?"
)

# E.164: a leading + and 7..15 digits.
_E164 = re.compile(r"^\+\d{7,15}$")


def build_reservation_prompt(place_name: str, datetime_str: str, party_size: int,
                             locale: str = "ru-RU", contact_name: str = "гость") -> str:
    """Return the agent system prompt for a restaurant reservation.

    Only ru-RU is templated today; other locales fall back to the Russian script
    with a note. ponytail: single-locale template — add per-locale strings here
    when a non-RU market is actually needed.
    """
    return _RU_SYSTEM_PROMPT.format(
        place=place_name, party=party_size, when=datetime_str, name=contact_name)


def book_table(place_name: str, phone_number: str, datetime_str: str, party_size: int,
               locale: str = "ru-RU", dry_run: bool = True, *,
               confirm_real_call: bool = False, agent_id: str | None = None,
               contact_name: str = "гость", key: str | None = None) -> dict:
    """Compose (and, only when explicitly told, place) a reservation call.

    Returns, on dry_run (DEFAULT True): {"dry_run": True, "payload": {...},
    "system_prompt": "...", "initial_greeting": "..."} — NO call is placed.

    A real call requires dry_run=False AND confirm_real_call=True AND agent_id.
    """
    # Validate at the trust boundary — bad input must never reach a dialer.
    if not place_name or not place_name.strip():
        raise ValueError("place_name is required")
    if not _E164.match(phone_number or ""):
        raise ValueError(f"phone_number must be E.164 (e.g. +14155551234), got {phone_number!r}")
    if not datetime_str or not datetime_str.strip():
        raise ValueError("datetime_str is required")
    if not isinstance(party_size, int) or party_size < 1:
        raise ValueError(f"party_size must be a positive int, got {party_size!r}")

    system_prompt = build_reservation_prompt(
        place_name, datetime_str, party_size, locale=locale, contact_name=contact_name)
    greeting = _RU_GREETING.format(place=place_name, party=party_size, when=datetime_str)

    payload = {
        "agentId": agent_id,
        "toNumber": phone_number,
        "systemPrompt": system_prompt,
        "initialGreeting": greeting,
    }

    if dry_run:
        return {
            "dry_run": True,
            "payload": payload,
            "system_prompt": system_prompt,
            "initial_greeting": greeting,
        }

    # --- live path (never exercised by tests) ---
    if not confirm_real_call:
        raise PermissionError(
            "Refusing to place a real call: pass confirm_real_call=True to dial for real.")
    if not agent_id:
        raise ValueError("agent_id is required to place a real call")
    result = client.place_call(payload, key=key)
    return {"dry_run": False, "payload": payload, "result": result}
