#!/usr/bin/env python3
"""Drive ONE real heavy-lane chat-sites build and verify it end-to-end.

Mirrors exactly what the live worker does for an inbound build message:
  hermes chat --quiet --query=<prompt>   (HERMES_HOME=~/.hermes-savedlab, env sourced)
then cleans the stdout with the SAME regexes the worker's hermes_bridge uses, so
the "reply" we check is byte-for-byte what the user would receive in iMessage.

Checks (printed as one JSON line):
  - built_in_turn : the reply contains a /s/<handle> URL (not a clarifying question)
  - clean         : no diff/chrome/ANSI/notice leak in the user-facing reply
  - http_200      : the deployed URL serves 200
  - html_bytes    : served document size
  - has_db_runtime: page injects window.dbQuery (apps only)
  - data_roundtrip: (apps) a generic CREATE/INSERT/SELECT/DROP on the app's own
                    Turso DB succeeds — proves the data layer is really wired
  - agent_tables  : (apps) the agent's OWN schema was applied (>=1 non-probe table)
  - ok            : all relevant checks passed for the requested kind

Records each built handle to probe_sites.jsonl for later cleanup. No deletion here
(the quality judge needs the URL live during a battery run).

Usage:
  build_probe.py --kind static|app --prompt "..." [--timeout 260] [--label x]
Exit 0 iff ok:true.  stdout = the JSON verdict (last line).
"""
import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.error

HOME = os.path.expanduser("~")
HHOME = os.path.join(HOME, ".hermes-savedlab")
HDIR = os.path.join(HOME, "hermes-agent")
ENVF = os.path.join(HHOME, ".env")
HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "probe_sites.jsonl")

# --- bridge reply-cleaning (kept in sync with worker/hermes_bridge.py) ----------
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]")
_NOTICE = re.compile(r"^[ \t]*⚠️?.*$", re.MULTILINE)
_FRAME = re.compile(r"^[ \t]*(?:[┊╭╰].*|session_id:.*)$", re.MULTILINE)


def clean_reply(stdout: str) -> str:
    c = _THINK.sub("", stdout)
    c = _ANSI.sub("", c)
    c = _NOTICE.sub("", c)
    c = _FRAME.sub("", c)
    c = re.sub(r"\n{3,}", "\n\n", c).strip()
    return c


def load_env() -> dict:
    env = dict(os.environ)
    with open(ENVF, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    env["HERMES_HOME"] = HHOME
    return env


def http(method, url, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"ERR {e}"


def data_proxy(base, handle, sql, args=None):
    return http("POST", f"{base}/site-data/{handle}", {"sql": sql, "args": args or []})


def run_build(prompt: str, timeout: int) -> tuple[int, str, str]:
    env = load_env()
    p = subprocess.run(
        [f"{HDIR}/venv/bin/python", f"{HDIR}/hermes", "chat", "--quiet", f"--query={prompt}"],
        cwd=HDIR, env=env, capture_output=True, text=True, timeout=timeout,
    )
    return p.returncode, p.stdout, p.stderr


URL_RE = re.compile(r"https://[a-z0-9-]+\.convex\.site/s/([a-z0-9-]+)", re.IGNORECASE)
# chrome/diff leak markers that must NOT survive cleaning into the user's reply
LEAK = ("@@ ", "\n+<", "+<!doctype", "┊", "╭", "╰", "session_id:", "\x1b", "→ b//tmp", "a//tmp/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["static", "app"], required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    v = {"kind": a.kind, "label": a.label, "ok": False, "ts": int(time.time())}
    t0 = time.time()
    try:
        rc, out, err = run_build(a.prompt, a.timeout)
    except subprocess.TimeoutExpired:
        v.update(error="hermes_timeout", elapsed=round(time.time() - t0, 1))
        print(json.dumps(v, ensure_ascii=False)); sys.exit(1)
    v["elapsed"] = round(time.time() - t0, 1)
    v["exit"] = rc

    reply = clean_reply(out)
    v["reply"] = reply[:600]
    v["clean"] = not any(m in reply for m in LEAK)

    handles = list(dict.fromkeys(URL_RE.findall(reply)))
    v["handles"] = handles
    v["built_in_turn"] = len(handles) >= 1
    if not handles:
        v["error"] = "no_url_in_reply"
        print(json.dumps(v, ensure_ascii=False)); sys.exit(1)

    handle = handles[0]
    base = "https://zany-tapir-501.convex.site"
    url = f"{base}/s/{handle}"
    v["url"] = url
    with open(MANIFEST, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"handle": handle, "kind": a.kind, "ts": v["ts"]}) + "\n")

    status, html = http("GET", url, timeout=30)
    v["http_200"] = status == 200
    v["html_bytes"] = len(html)
    v["has_db_runtime"] = "window.dbQuery" in html
    v["has_form_or_dbquery"] = ("<form" in html.lower()) or ("dbquery(" in html.lower())

    if a.kind == "static":
        v["ok"] = bool(v["clean"] and v["built_in_turn"] and v["http_200"]
                       and v["html_bytes"] >= 2000 and not v["has_db_runtime"])
    else:  # app: prove the real data layer works end-to-end
        rt = False
        agent_tables = 0
        s, b = data_proxy(base, handle,
                          "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        if s == 200:
            try:
                rows = json.loads(b).get("rows", [])
                agent_tables = len([r for r in rows if r.get("name") != "_probe"])
            except Exception:  # noqa: BLE001
                pass
        # generic round-trip on the app's OWN database
        data_proxy(base, handle, "CREATE TABLE IF NOT EXISTS _probe(x integer)")
        si, bi = data_proxy(base, handle, "INSERT INTO _probe(x) VALUES (?)", [4242])
        ss, bs = data_proxy(base, handle, "SELECT x FROM _probe ORDER BY x DESC")
        try:
            ins_ok = si == 200 and json.loads(bi).get("rowsAffected", 0) >= 1
            sel_ok = ss == 200 and any(r.get("x") == 4242 for r in json.loads(bs).get("rows", []))
            rt = bool(ins_ok and sel_ok)
        except Exception:  # noqa: BLE001
            rt = False
        data_proxy(base, handle, "DROP TABLE IF EXISTS _probe")
        v["data_roundtrip"] = rt
        v["agent_tables"] = agent_tables
        v["ok"] = bool(v["clean"] and v["built_in_turn"] and v["http_200"]
                       and v["has_db_runtime"] and v["has_form_or_dbquery"]
                       and rt and agent_tables >= 1)

    print(json.dumps(v, ensure_ascii=False))
    sys.exit(0 if v["ok"] else 1)


if __name__ == "__main__":
    main()
