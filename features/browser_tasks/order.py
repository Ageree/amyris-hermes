#!/usr/bin/env python3
"""
order.py — local browser-use order engine for Yandex services (food / grocery / taxi).

Unifies the three flows (one file, per-service templates) and adds the two things v1
lacked: a PAYMENT-CAPABLE attach mode and an explicit pay step.

Modes:
  • profile (default): a FRESH headless profile, NO login → builds the cart/route and
    stops before the auth/pay wall ("path A handoff"). Safe, no money, no account.
  • attach (--attach / ORDER_CDP_URL): connect to the operator's PERSISTENT logged-in
    Chrome (launched separately with --remote-debugging-port) via Browser(cdp_url=…).
    Login + linked card live in that profile → checkout can actually go through.
  • --pay: drive THROUGH payment with the ALREADY-LINKED card. Hard safety guard:
    NEVER type card numbers — if asked to ADD/enter a card → NEED_CARD and stop; a
    bank/3DS code screen → NEED_3DS and stop; web that demands the app → WEB_NO_ORDER.

ponytail: local single-host browser-use. Upgrade path = browser-use CLOUD over a CDP
endpoint + RU-mobile proxy + per-user profile_id (swap ORDER_CDP_URL / BU envs, no code
change). Real-money payment is gated upstream by per-order operator confirmation.

Run (one JSON object on stdout; logs to stderr):
  ~/.eve-orders/.venv/bin/python order.py --service taxi --from "Мичуринский 56" --to "3-я Фрунзенская 4"
  …                                        --service food --address "Тверская 7" --item "бургер"
  …                                        --service grocery --address "Тверская 7" --item "молоко"
  add --attach --pay   to complete a real paid order on the persistent profile.
"""
from __future__ import annotations  # `str | None` annotations stay portable to py3.9

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from string import Template

ENV_FILE = Path.home() / ".hermes-savedlab" / ".env"
DEFAULT_CDP = "http://127.0.0.1:9333"


def load_env(path: Path) -> None:
    # OVERRIDE (not setdefault): the session may export a stale sk-cp- MiniMax Token
    # Plan key that 401s against the OpenRouter base_url; the .env file is the matched set.
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


# --- per-service task templates (vision-mode; browser-use self-heals selectors) -------
FOOD = Template(
    """Это автоматизация заказа доставки еды на Яндекс.Еда (use_vision — смотри на скриншоты).
Адрес доставки: $address. Что заказать: $item.

1. Открой https://eda.yandex.ru
2. Укажи адрес $address: введи в поле, дождись подсказок, ВЫБЕРИ подсказку С НОМЕРОМ ДОМА
   (например «Тверская улица, 7, Москва») — кликни по строке целиком. НЕ выбирай улицу без
   дома (кнопка «Ок» останется серой). После выбора с домом нажми «Ок». НЕ нажимай Escape.
3. Открой любой открытый ресторан (например «Вкусно – и точка»).
4. Добавь в корзину: $item. Если откроется карточка с опциями — жми жёлтую «Добавить» внизу
   (не «Добавить в подборку» — это сердечко).
5. Убедись, что в корзине есть позиция и сумма.
$guard"""
)

GROCERY = Template(
    """Это автоматизация заказа продуктов в Яндекс Лавке (use_vision — смотри на скриншоты).
Адрес доставки: $address. Что купить: $item.

1. Открой https://lavka.yandex.ru
2. Укажи адрес доставки $address: введи в поле адреса, дождись подсказок, ВЫБЕРИ подсказку
   С НОМЕРОМ ДОМА и подтверди (кнопка «Сохранить»/«Готово»/«Ок»). НЕ нажимай Escape.
3. Найди товар «$item»: через иконку поиска (лупа) введи название, ИЛИ через каталог.
4. На карточке товара нажми кнопку добавления в корзину (плюс «+» или «В корзину»).
   Если попросит выбрать вес/вариант — выбери любой и добавь.
5. Открой корзину (значок корзины справа/сверху). Убедись, что есть позиция и сумма.
$guard"""
)

TAXI = Template(
    """Это автоматизация вызова такси на Яндекс Такси (use_vision — смотри на скриншоты).
Маршрут: откуда «$origin», куда «$dest».

1. Открой https://taxi.yandex.ru
2. Поле «Откуда»: очисти автоадрес, напечатай «$origin», дождись подсказок. ВЫБЕРИ вариант
   с типом «Дом» и нужным номером дома — лучше клавиатурой: стрелка вниз (ArrowDown) до пункта,
   затем Enter. Убедись по скриншоту, что адрес ЗАФИКСИРОВАН (поле показывает адрес, список
   закрылся). НЕ нажимай Escape (он сбрасывает поля).
3. Поле «Куда»: так же напечатай «$dest» и зафиксируй подсказку с домом. Если точного дома нет —
   выбери ближайший вариант той же улицы, НЕ нажимай Escape.
4. Дождись расчёта тарифов. Посмотри цену «Эконом».
$guard"""
)

SERVICES = {"food": FOOD, "grocery": GROCERY, "taxi": TAXI}

# stop-before-pay guard (profile mode / no --pay): build the cart/route, report, stop.
GUARD_NOPAY = (
    "ВАЖНО: НЕ нажимай «Войти»/«Заказать»/«Вызвать», НЕ вводи телефон, НЕ логинься, НЕ оплачивай. "
    "Как только видишь корзину с суммой (для такси — тарифы с ценой) — задача выполнена, вызови "
    "done с итоговой суммой/ценой и составом/маршрутом. Капча → останови задачу и сообщи в done."
)

# pay guard (--pay, attach to a logged-in profile): complete with the ALREADY-LINKED card.
GUARD_PAY = (
    "Доведи заказ до конца: оформи и ОПЛАТИ уже привязанной картой (для такси — нажми "
    "«Заказать»/«Вызвать»). КРИТИЧНО ПО БЕЗОПАСНОСТИ: НИКОГДА не вводи номера карт/CVV. Если "
    "просят ДОБАВИТЬ или ВВЕСТИ данные карты — НЕ вводи, останови задачу и верни 'NEED_CARD'. "
    "Если открылась страница банка/3DS с вводом кода — НЕ вводи, верни 'NEED_3DS' с описанием. "
    "Если доступны только «Наличные» (карта не привязана) — верни 'NEED_CARD'. Если веб требует "
    "приложение и не даёт оформить — верни 'WEB_NO_ORDER'. Если заказ создан и оплачен — верни "
    "'ORDER_PLACED' с суммой и способом оплаты. Капча → останови и сообщи."
)

# login-wall detect (appended to BOTH guards). A per-user container's persistent Chrome
# profile may not be logged into Yandex yet (first order). The agent must NEVER log in
# itself — the USER does that once via the live-view handoff (see docs/eve-fleet-onboarding.md)
# — it returns NEED_LOGIN so the poller can surface the handoff URL through the user's channel.
GUARD_LOGIN = (
    " ОТДЕЛЬНО (вход в аккаунт): если для продолжения Яндекс требует ВОЙТИ — открылась "
    "passport.yandex.ru, экран входа по номеру телефона/коду из SMS, а аккаунт НЕ залогинен — "
    "НЕ логинься сам и НЕ вводи телефон/код, верни 'NEED_LOGIN' и останови задачу."
)


def build_task(service: str, params: dict, pay: bool) -> str:
    tmpl = SERVICES[service]
    guard = (GUARD_PAY if pay else GUARD_NOPAY) + GUARD_LOGIN
    return tmpl.substitute(**params, guard=guard)


def resolve_cdp(attach: bool, env) -> str | None:
    """attach mode: ORDER_CDP_URL (the persistent logged-in Chrome) wins; else --attach
    falls back to the default port; else None → a fresh profile. Pure so it's unit-checkable."""
    return env.get("ORDER_CDP_URL") or (DEFAULT_CDP if attach else None)


def make_llm(model, base_url, key):
    """M3 (OpenRouter) with reasoning OFF — browser-use's ChatOpenAI has no reasoning knob,
    and M3's default reasoning makes each vision step ~75s. OpenRouter kill-switch =
    extra_body={'reasoning':{'enabled':False}} (lowest reasoning_tokens on minimax-m3)."""
    from browser_use.llm import ChatOpenAI

    class ChatM3(ChatOpenAI):
        def get_client(self):
            client = super().get_client()
            completions = client.chat.completions
            orig = completions.create

            async def create(*a, **kw):
                eb = dict(kw.get("extra_body") or {})
                eb.setdefault("reasoning", {"enabled": False})
                kw["extra_body"] = eb
                return await orig(*a, **kw)

            completions.create = create
            return client

    return ChatM3(model=model, base_url=base_url, api_key=key, temperature=0.2)


def service_params(args) -> dict:
    if args.service == "taxi":
        if not (args.origin and args.dest):
            raise SystemExit("taxi needs --from and --to")
        return {"origin": args.origin, "dest": args.dest}
    if not args.address:
        raise SystemExit(f"{args.service} needs --address")
    return {"address": args.address, "item": args.item or "что-нибудь популярное"}


async def run(args) -> dict:
    load_env(ENV_FILE)
    from browser_use import Agent

    key = os.environ.get("MINIMAX_API_KEY")
    base_url = os.environ.get("MINIMAX_BASE_URL", "https://openrouter.ai/api/v1")
    model = args.model or os.environ.get("MINIMAX_MODEL", "minimax/minimax-m3")
    if not key:
        return {"ok": False, "status": "error", "error": "MINIMAX_API_KEY not set"}

    params = service_params(args)
    task = build_task(args.service, params, args.pay)
    llm = make_llm(model, base_url, key)

    # attach to the persistent logged-in Chrome (payment-capable) vs a fresh profile.
    cdp = resolve_cdp(args.attach, os.environ)
    agent_kw = dict(task=task, llm=llm, use_vision=True, generate_gif=False)
    if cdp:
        from browser_use import Browser
        agent_kw["browser"] = Browser(cdp_url=cdp)
        mode = f"attach:{cdp}"
    else:
        from browser_use import BrowserProfile
        agent_kw["browser_profile"] = BrowserProfile(
            headless=not args.headed, locale="ru-RU", timezone_id="Europe/Moscow"
        )
        mode = "profile:fresh"
    print(f"[order] service={args.service} mode={mode} pay={args.pay}", file=sys.stderr)

    agent = Agent(**agent_kw)
    history = await agent.run(max_steps=args.max_steps)
    final = history.final_result() or ""
    success = history.is_successful()
    urls = history.urls() if hasattr(history, "urls") else []
    return {
        "ok": success is True,
        "status": "done" if success is True else ("failed" if success is False else "incomplete"),
        "service": args.service,
        "params": params,
        "paid": args.pay and "ORDER_PLACED" in final,
        # NEED_LOGIN first: an un-logged-in profile is the ROOT block (NEED_CARD is moot
        # until the user is signed in) → it wins, and the poller triggers the handoff.
        "needs": next((m for m in ("NEED_LOGIN", "NEED_CARD", "NEED_3DS", "WEB_NO_ORDER") if m in final), None),
        "final_result": final,
        "steps": history.number_of_steps() if hasattr(history, "number_of_steps") else None,
        "last_url": urls[-1] if urls else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", choices=list(SERVICES))
    ap.add_argument("--address", default=None, help="food/grocery delivery address")
    ap.add_argument("--item", default=None, help="food dish / grocery product")
    ap.add_argument("--from", dest="origin", default=None, help="taxi pickup")
    ap.add_argument("--to", dest="dest", default=None, help="taxi destination")
    ap.add_argument("--attach", action="store_true", help="attach to persistent Chrome (ORDER_CDP_URL or :9333)")
    ap.add_argument("--pay", action="store_true", help="complete payment with the linked card (needs --attach/login)")
    ap.add_argument("--max-steps", type=int, default=34)
    ap.add_argument("--model", default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--check-templates", action="store_true", help="offline: build all templates, assert wiring")
    args = ap.parse_args()

    if args.check_templates:
        # offline self-check: every service builds a task with its params substituted,
        # both guards differ, pay guard carries the card-safety stop tokens.
        assert "Тверская 7" in build_task("food", {"address": "Тверская 7", "item": "бургер"}, False)
        assert "молоко" in build_task("grocery", {"address": "Тверская 7", "item": "молоко"}, False)
        t = build_task("taxi", {"origin": "А", "dest": "Б"}, True)
        assert "А" in t and "Б" in t
        assert "NEED_CARD" in build_task("food", {"address": "x", "item": "y"}, True)
        # NEED_LOGIN detectable in BOTH modes (the container login handoff trigger).
        assert "NEED_LOGIN" in build_task("food", {"address": "x", "item": "y"}, False)
        assert "NEED_LOGIN" in build_task("taxi", {"origin": "А", "dest": "Б"}, True)
        assert "НЕ оплачивай" in build_task("food", {"address": "x", "item": "y"}, False)
        assert "$" not in build_task("taxi", {"origin": "А", "dest": "Б"}, False), "unsubstituted template var"
        # service → correct site (food→eda, grocery→lavka, taxi→taxi).
        assert "eda.yandex.ru" in build_task("food", {"address": "x", "item": "y"}, False)
        assert "lavka.yandex.ru" in build_task("grocery", {"address": "x", "item": "y"}, False)
        assert "taxi.yandex.ru" in build_task("taxi", {"origin": "А", "dest": "Б"}, False)
        # attach branch: ORDER_CDP_URL wins; --attach → default port; neither → fresh.
        assert resolve_cdp(False, {}) is None, "no attach, no env → fresh profile"
        assert resolve_cdp(True, {}) == DEFAULT_CDP, "--attach → default CDP port"
        assert resolve_cdp(False, {"ORDER_CDP_URL": "http://127.0.0.1:9333"}) == "http://127.0.0.1:9333"
        assert resolve_cdp(True, {"ORDER_CDP_URL": "http://x:1"}) == "http://x:1", "env wins over default"
        print("[order] templates SELF-CHECK PASS", file=sys.stderr)
        sys.exit(0)

    if not args.service:
        ap.error("--service is required to run an order")
    try:
        res = asyncio.run(run(args))
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "status": "error", "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
