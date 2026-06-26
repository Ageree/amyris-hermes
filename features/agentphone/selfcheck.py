"""Runnable self-check for the AgentPhone integration. SAFE: no money, no calls.

Steps (all assert-based):
  1. GET /v1/usage            -> 200 JSON with a plan
  2. GET /v1/agents/voices    -> non-empty list; report Russian-voice availability
  3. create_agent(ru-RU)      -> throwaway agent created
  4. list_agents()            -> the new agent appears
  5. delete_agent()           -> the agent is gone
  6. book_table(dry_run=True) -> payload has toNumber + a Russian systemPrompt, NO call

Run (key via env or AGENTPHONE_SECRETS_FILE):
    AGENTPHONE_SECRETS_FILE=/path/secrets.env python3 -m features.agentphone.selfcheck
"""
from __future__ import annotations

import sys
import time

from . import client, reservation


def _has_cyrillic(s: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in s)


def main() -> int:
    print("== AgentPhone self-check (safe: no money, no calls) ==")

    # 1) usage
    usage = client.get_usage()
    assert isinstance(usage, dict) and "plan" in usage, f"bad usage payload: {usage}"
    print(f"[1] usage OK — plan={usage['plan'].get('name')} "
          f"numbers={usage.get('numbers')} "
          f"voiceMinutes/mo={usage['plan'].get('limits', {}).get('voiceMinutesPerMonth')}")

    # 2) voices
    voices = client.list_voices()
    assert isinstance(voices, list) and voices, f"voices not a non-empty list: {type(voices)}"
    accents = {v.get("accent") for v in voices}
    russian_voices = [v for v in voices
                      if "russ" in str(v.get("accent", "")).lower()
                      or "russ" in str(v.get("voice_name", "")).lower()]
    print(f"[2] voices OK — {len(voices)} voices, "
          f"providers={sorted({v.get('provider') for v in voices})}")
    print(f"    Russian-labeled voices: {len(russian_voices)} "
          f"(accents present: {sorted(a for a in accents if a)})")

    # pick a multilingual provider voice (elevenlabs/minimax can speak ru text)
    voice_id = next((v["voice_id"] for v in voices
                     if v.get("provider") in ("elevenlabs", "minimax")), voices[0]["voice_id"])

    # 3) create throwaway ru-RU agent (deleted in finally)
    agent_id = None
    try:
        name = f"eve-selfcheck-{int(time.time())}"
        sys_prompt = reservation.build_reservation_prompt(
            "Тестовый ресторан", "сегодня в 19:00", 2)
        created = client.create_agent(name, sys_prompt, language="ru-RU", voice=voice_id)
        agent_id = created.get("id") or created.get("agentId")
        assert agent_id, f"create_agent returned no id: {created}"
        print(f"[3] create_agent OK — id={agent_id} "
              f"name={created.get('name')} lang={created.get('language')} "
              f"voiceMode={created.get('voiceMode')} voice={created.get('voice')}")

        # 4) appears in list
        ids = {a.get("id") for a in client.list_agents()}
        assert agent_id in ids, f"new agent {agent_id} not in list_agents(): {ids}"
        print(f"[4] list_agents OK — {len(ids)} agents, new one present")

        # 5) delete + confirm gone
        client.delete_agent(agent_id)
        ids_after = {a.get("id") for a in client.list_agents()}
        assert agent_id not in ids_after, f"agent {agent_id} still present after delete"
        print("[5] delete_agent OK — agent gone")
        agent_id = None  # already deleted; skip finally cleanup
    finally:
        if agent_id:
            try:
                client.delete_agent(agent_id)
                print(f"    (cleanup) deleted throwaway agent {agent_id}")
            except Exception as e:  # noqa: BLE001 - best-effort cleanup
                print(f"    (cleanup) WARN: could not delete {agent_id}: {e}")

    # 6) book_table dry-run — composes payload, NO call placed
    out = reservation.book_table(
        place_name="Кафе Пушкинъ", phone_number="+74951234567",
        datetime_str="28 июня в 20:00", party_size=4, dry_run=True)
    assert out["dry_run"] is True, "book_table must default to dry_run"
    pl = out["payload"]
    assert pl["toNumber"] == "+74951234567", f"toNumber missing/wrong: {pl}"
    assert _has_cyrillic(pl["systemPrompt"]), "systemPrompt is not Russian"
    assert "Кафе Пушкинъ" in pl["systemPrompt"], "place name not in systemPrompt"
    assert _has_cyrillic(pl["initialGreeting"]), "greeting is not Russian"
    print("[6] book_table(dry_run=True) OK — composed payload, NO call placed")
    print(f"    toNumber={pl['toNumber']}")
    print(f"    systemPrompt[:90]={pl['systemPrompt'][:90]!r}")
    print(f"    initialGreeting[:80]={pl['initialGreeting'][:80]!r}")

    # guard: a real call must be impossible without the explicit flags
    try:
        reservation.book_table("X", "+74951234567", "now", 2, dry_run=False)
        print("[guard] FAIL — book_table placed/attempted a call without confirm_real_call")
        return 1
    except PermissionError:
        print("[guard] OK — dry_run=False without confirm_real_call is refused")

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
