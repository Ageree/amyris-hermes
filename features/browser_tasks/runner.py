#!/usr/bin/env python3
"""Parametrized browser-use task runner — reusable templates, use_vision=True.

The generated GIF (``<gif_dir>/<name>.gif``) IS the screen recording = QA evidence.
LLM = minimax/minimax-m3 via OpenRouter (MINIMAX_* env in ~/.hermes-savedlab/.env;
those vars actually point at OpenRouter — see ground truth). Vision mode is on
because it RELIABLY drives Yandex address-autocomplete widgets where DOM mode fails.

Each template STOPS before any irreversible action (no pay, no submit, no send).
The only way past that line is the explicit ``--allow-irreversible`` flag (plumbing
for real operator-authorized runs; never used for QA).

Two browser modes, mirroring the prototypes:
  * attach  (--cdp http://127.0.0.1:9333) → reuse a persistent logged-in Chrome.
  * own     (--own-chrome, default)       → launch real Chrome, fresh profile.

CLI:
  runner.py <template> [--param k=v ...] [--cdp URL | --own-chrome]
            [--max-steps N] [--gif PATH] [--conv PATH] [--allow-irreversible]

Live QA-with-GIF commands the lead runs (own Chrome, fresh profile, NOT logged in →
stops at the login/checkout wall by design):

  BU=/Users/saveliy/.claude/jobs/ea35b02a/tmp/bu-venv/bin/python
  R=/Users/saveliy/Documents/Amyris/.claude/worktrees/eve-core-rebuild/features/browser_tasks/runner.py
  $BU $R delivery_order --param address='Москва, Тверская улица, 1' --own-chrome --max-steps 18
  $BU $R job_autoapply  --param query='python developer'           --own-chrome --max-steps 16

Then inspect the GIF written to features/browser_tasks/runs/<template>.gif.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
from string import Template

HERE = pathlib.Path(__file__).parent
TEMPLATE_DIR = HERE / "templates"
RUNS_DIR = HERE / "runs"
DEFAULT_ENV = os.path.expanduser("~/.hermes-savedlab/.env")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Per-template contract: required params + defaults for optional ones.
TEMPLATES: dict[str, dict] = {
    "delivery_order": {
        "required": ["address"],
        "defaults": {"dish": "любое доступное блюдо"},
    },
    "job_autoapply": {
        "required": ["query"],
        "defaults": {"location": ""},
    },
}

# The hard stop. This is the whole point of the layer: never cross the line.
SAFE_GUARD = (
    "СТОП-ПРАВИЛО (КРИТИЧНО, НЕ НАРУШАЙ): это тест — НЕ совершай необратимых "
    "действий. НЕ нажимай кнопки оплаты/оформления/отправки («Оформить заказ», "
    "«Оплатить», «Заказать», «Отправить отклик», финальную «Откликнуться»). "
    "Остановись РОВНО на экране, где видны итог и кнопка финального действия, и "
    "верни итог. Если требуется вход / номер телефона / SMS-код / капча "
    "(SmartCaptcha) — ОСТАНОВИСЬ, опиши что именно появилось и на каком шаге."
)

# Only reachable via --allow-irreversible (operator-authorized). Plumbing only.
ALLOW_GUARD = (
    "РАЗРЕШЕНИЕ ОПЕРАТОРА: явно разрешено довести задачу до конца, включая "
    "финальное действие (оплата/отправка отклика). Действуй аккуратно. Если "
    "запросят данные карты/3DS/SMS, которых у тебя нет — остановись и опиши экран."
)


def env_from_file(path: str, key: str) -> str | None:
    """Read one KEY=value line from a dotenv file (mirror of the prototypes)."""
    p = pathlib.Path(path)
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_env(env_path: str = DEFAULT_ENV) -> tuple[str, str, str]:
    """Return (api_key, base_url, model) from the dotenv. Fail fast if missing."""
    key = env_from_file(env_path, "MINIMAX_API_KEY")
    base = env_from_file(env_path, "MINIMAX_BASE_URL")
    model = env_from_file(env_path, "MINIMAX_MODEL")
    if not (key and base and model):
        raise RuntimeError(
            f"missing MINIMAX_* in {env_path}: "
            f"key={bool(key)} base={bool(base)} model={bool(model)}"
        )
    return key, base, model


def list_templates() -> list[str]:
    """Names of available templates (those with both a .txt and a contract)."""
    on_disk = {p.stem for p in TEMPLATE_DIR.glob("*.txt")}
    return sorted(on_disk & set(TEMPLATES))


def _derive(name: str, subst: dict[str, str]) -> dict[str, str]:
    """Return a NEW dict with template-specific derived fields filled in."""
    out = dict(subst)
    if name == "job_autoapply":
        loc = (out.get("location") or "").strip()
        out["location_clause"] = f" в городе {loc}" if loc else ""
        out["location_step"] = f" Укажи город: {loc}." if loc else ""
    return out


def render_task(name: str, params: dict[str, str], allow_irreversible: bool = False) -> str:
    """Render a template to the final task prompt. Validates required params.

    Uses string.Template ($-placeholders) so Russian prose with stray braces is
    never misread as a format field.
    """
    if name not in TEMPLATES:
        raise KeyError(f"unknown template {name!r}; available: {list_templates()}")
    spec = TEMPLATES[name]
    missing = [r for r in spec["required"] if not (params.get(r) or "").strip()]
    if missing:
        raise ValueError(f"template {name!r} missing required param(s): {missing}")

    subst = {**spec["defaults"], **params}
    subst = _derive(name, subst)
    subst["guard"] = ALLOW_GUARD if allow_irreversible else SAFE_GUARD

    raw = (TEMPLATE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    rendered = Template(raw).safe_substitute(subst)
    if "$" in rendered:  # an unresolved placeholder slipped through
        leftover = [w for w in rendered.split() if w.startswith("$")]
        raise ValueError(f"unresolved placeholder(s) in {name!r}: {leftover}")
    return rendered.strip()


def build_browser(cdp_url: str | None, chrome_path: str | None):
    """Construct a Browser (attach if cdp_url, else launch real Chrome). Lazy:
    construction does NOT connect/launch — that happens in agent.run()."""
    from browser_use import Browser

    if cdp_url:
        return Browser(cdp_url=cdp_url)
    return Browser(executable_path=chrome_path or CHROME, headless=False, user_agent=None)


def build_agent(
    name: str,
    params: dict[str, str],
    *,
    cdp_url: str | None = None,
    chrome_path: str | None = None,
    gif_path: str | None = None,
    conv_path: str | None = None,
    allow_irreversible: bool = False,
    env_path: str = DEFAULT_ENV,
    llm=None,
    step_timeout: int = 120,
    max_actions_per_step: int = 4,
):
    """Build a browser-use Agent with use_vision=True + a generate_gif path.

    Does NOT call .run(). Returns (agent, gif_path). The GIF path is the QA
    screen recording; browser-use writes it when the run finishes.
    """
    from browser_use import Agent, ChatOpenAI

    task = render_task(name, params, allow_irreversible=allow_irreversible)
    if llm is None:
        key, base, model = load_env(env_path)
        llm = ChatOpenAI(model=model, base_url=base, api_key=key)
    gif_path = gif_path or str(RUNS_DIR / f"{name}.gif")
    browser = build_browser(cdp_url, chrome_path)
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        use_vision=True,                 # vision drives Yandex autocomplete reliably
        generate_gif=gif_path,           # the GIF == screen recording == QA evidence
        save_conversation_path=conv_path,
        max_actions_per_step=max_actions_per_step,
        step_timeout=step_timeout,
    )
    return agent, gif_path


async def run_task(name: str, params: dict[str, str], *, max_steps: int = 18, **kw) -> dict:
    """Build the agent and actually run it. Prints + returns a result summary."""
    agent, gif_path = build_agent(name, params, **kw)
    pathlib.Path(gif_path).parent.mkdir(parents=True, exist_ok=True)
    history = await agent.run(max_steps=max_steps)
    summary = {
        "template": name,
        "done": history.is_done(),
        "final": history.final_result(),
        "urls": history.urls()[-5:],
        "errors": [e for e in history.errors() if e][-5:],
        "gif": gif_path,
    }
    print(f"\n===== RESULT ({name}) =====", flush=True)
    for k, v in summary.items():
        print(f"{k}: {v}", flush=True)
    return summary


def _parse_params(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"--param must be k=v, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="browser-use task runner (use_vision=True, GIF=QA)")
    ap.add_argument("template", choices=list_templates(), help="task template name")
    ap.add_argument("--param", action="append", default=[], help="template param k=v (repeatable)")
    ap.add_argument("--cdp", help="attach to a running Chrome at this CDP url")
    ap.add_argument("--own-chrome", action="store_true", help="launch real Chrome (default)")
    ap.add_argument("--chrome-path", default=CHROME)
    ap.add_argument("--max-steps", type=int, default=18)
    ap.add_argument("--gif", help="output GIF path (default features/browser_tasks/runs/<name>.gif)")
    ap.add_argument("--conv", help="save_conversation_path (debug)")
    ap.add_argument("--allow-irreversible", action="store_true",
                    help="OPERATOR-AUTHORIZED: permit the final pay/submit action")
    ap.add_argument("--env", default=DEFAULT_ENV)
    args = ap.parse_args(argv)

    asyncio.run(run_task(
        args.template,
        _parse_params(args.param),
        max_steps=args.max_steps,
        cdp_url=args.cdp,
        chrome_path=args.chrome_path,
        gif_path=args.gif,
        conv_path=args.conv,
        allow_irreversible=args.allow_irreversible,
        env_path=args.env,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
