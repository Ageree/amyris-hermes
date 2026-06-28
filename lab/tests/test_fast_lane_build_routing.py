"""looks_like_build_request routes "build me a site/app" away from the fast lane.

Regression for the chat-sites go-live bug: the operator texted "сделай мне
лендинг…" / "просто сделай лендинг" and the SLIM fast lane (no create-site skill,
no terminal) just chatted and promised to build "later" — which never came. The
prefilter must send those to the heavy Hermes lane (where the skill + publish.py
live), exactly like contains_url does for links, WITHOUT dragging ordinary chat
along (a false positive only costs a slower turn, but we still don't want every
message escalated).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skeleton"))

from fast_lane import looks_like_build_request as f  # noqa: E402

# The operator's ACTUAL phrases that went unbuilt, plus common build intents.
BUILD = [
    "Сделай мне лендинг для моих часов viceron Constantine В стиле этого сайта",
    "Просто сделай лендинг с этими часами",
    "сделай мне сайт-визитку",
    "построй гостевую книгу для команды",
    "запили простенький one-pager про кофейню",
    "создай мне портфолио",
    "сделай опрос для друзей",
    "сделай мне страничку с резюме",
    "сделай счётчик посещений",
    "make me a landing page for my startup",
    "build a guestbook app",
    "create a poll for the team",
]

# Ordinary chat / non-build actions must STAY on the fast lane.
CHAT = [
    "привет! как сам?",
    "посоветуй три коротких фильма на вечер",
    "Неплохо, какой браузер ты используешь?",
    "расскажи про свою работу",
    "сделай погромче музыку",   # build verb, no site noun
    "купи мне билет",            # action, not a build
    "happy birthday!",          # 'app' substring trap
    "что нового?",
]


def test_build_requests_route_to_hermes():
    for t in BUILD:
        assert f(t), f"should defer to Hermes: {t!r}"


def test_plain_chat_stays_on_fast_lane():
    for t in CHAT:
        assert not f(t), f"should stay fast: {t!r}"


if __name__ == "__main__":  # assert-based self-check, no framework needed
    test_build_requests_route_to_hermes()
    test_plain_chat_stays_on_fast_lane()
    print(f"OK: {len(BUILD)} build / {len(CHAT)} chat routed correctly")
