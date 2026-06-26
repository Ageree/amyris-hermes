#!/usr/bin/env python3
"""Offline self-check for the browser task layer. NO live browser run.

Verifies: runner compiles, templates load, params render + validate, the safety
guard is present (and swaps under --allow-irreversible), and build_agent yields a
browser-use Agent with use_vision=True + a generate_gif path WITHOUT calling .run().

Run:  /Users/saveliy/.claude/jobs/ea35b02a/tmp/bu-venv/bin/python \
        features/browser_tasks/selfcheck.py
"""
import py_compile
import sys
import pathlib

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

import runner  # noqa: E402

ok = 0


def check(label, cond):
    global ok
    assert cond, f"FAIL: {label}"
    ok += 1
    print(f"  ok  {label}")


# 1) runner compiles
py_compile.compile(str(HERE / "runner.py"), doraise=True)
print("[1] py_compile runner.py -> OK")

# 2) templates load
names = runner.list_templates()
print(f"[2] templates: {names}")
check("delivery_order present", "delivery_order" in names)
check("job_autoapply present", "job_autoapply" in names)

# 3) render delivery_order with params; required validation; guard present
task = runner.render_task("delivery_order", {"address": "Москва, Тверская улица, 1"})
check("delivery: address substituted", "Москва, Тверская улица, 1" in task)
check("delivery: dish default substituted", "любое доступное блюдо" in task)
check("delivery: SAFE_GUARD present", "СТОП-ПРАВИЛО" in task)
check("delivery: no leftover $placeholder", "$" not in task)

# 4) render job_autoapply with derived location fields
job = runner.render_task("job_autoapply", {"query": "python developer", "location": "Москва"})
check("job: query substituted", "python developer" in job)
check("job: location derived clause", "в городе Москва" in job)
check("job: SAFE_GUARD present", "СТОП-ПРАВИЛО" in job)
check("job: no leftover $placeholder", "$" not in job)

# 4b) job without optional location renders clean (no leftover placeholders)
job2 = runner.render_task("job_autoapply", {"query": "data analyst"})
check("job(no loc): renders, no leftover $", "$" not in job2)

# 5) required-param validation fails fast
try:
    runner.render_task("delivery_order", {})
    check("delivery: missing address raises", False)
except ValueError:
    check("delivery: missing address raises ValueError", True)

# 6) unknown template raises
try:
    runner.render_task("nope", {"x": "y"})
    check("unknown template raises", False)
except KeyError:
    check("unknown template raises KeyError", True)

# 7) allow flag swaps the guard (plumbing — never used in QA)
allow = runner.render_task("delivery_order", {"address": "X"}, allow_irreversible=True)
check("allow: SAFE_GUARD gone", "СТОП-ПРАВИЛО" not in allow)
check("allow: ALLOW_GUARD present", "РАЗРЕШЕНИЕ ОПЕРАТОРА" in allow)

# 8) env wiring resolves to the OpenRouter minimax model
key, base, model = runner.load_env()
check("env: model is minimax", "minimax" in model.lower())
print(f"[8] env -> model={model} base={base} key={key[:6]}…")

# 9) build_agent builds Agent(use_vision=True, generate_gif=...) WITHOUT .run()
#    Use an explicit fake-key LLM (constructing it makes no network call) so the
#    check is hermetic and never touches the browser or the network.
from browser_use import ChatOpenAI  # noqa: E402
fake_llm = ChatOpenAI(model=model, base_url=base, api_key="sk-selfcheck-not-real")

for tname, params in [
    ("delivery_order", {"address": "Москва, Тверская улица, 1"}),
    ("job_autoapply", {"query": "python developer"}),
]:
    agent, gif = runner.build_agent(tname, params, llm=fake_llm)
    check(f"{tname}: use_vision is True", agent.settings.use_vision is True)
    check(f"{tname}: generate_gif set to our path", agent.settings.generate_gif == gif)
    check(f"{tname}: gif default under runs/", gif.endswith(f"runs/{tname}.gif"))
    check(f"{tname}: task carries SAFE_GUARD into agent", "СТОП-ПРАВИЛО" in agent.task)
    # we never called .run(); agent has no completed history
    check(f"{tname}: .run() not invoked", not getattr(agent, "_done", False))

print(f"\nSELF-CHECK PASSED — {ok} assertions OK")
