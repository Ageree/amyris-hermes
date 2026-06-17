---
name: browser-harness
description: Open, browse, and interact with any website in a REAL browser (click, type, scroll, read pages, fill forms, watch pages render). Use this whenever a task needs a live browser — opening a URL, navigating a site, logging in, reading a page that needs JS, or any web interaction. This is your only browser; there is no browser_navigate tool.
version: 0.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [browser, web, automation]
---

# Browser (browser-harness)

You drive a real Chrome over CDP through the `browser-harness` CLI, using your
`terminal` tool. The browser is already running headless in this container;
`BU_NAME` (your per-user id) and `BU_CDP_URL` are already set in your environment.
You are the only brain — the harness has no LLM of its own.

## How to drive it

Run one `terminal` command per group of actions. Feed Python via a heredoc; the
helpers are already in scope (no imports). Always `print(...)` whatever you need
to read back — only stdout comes back to you.

```bash
browser-harness <<'PY'
new_tab("https://example.com")   # use new_tab FIRST, not goto_url
wait_for_load()
print(page_info())               # -> {'url':..., 'title':..., ...}
PY
```

## Helpers (in scope)

- Tabs: `new_tab(url)` (open first), `goto_url(url)`, `list_tabs()`, `switch_tab(i)`, `close_tab()`
- Read: `page_info()`, `wait_for_load()`, `wait_for_element(sel)`, `wait_for_network_idle()`, `capture_screenshot()`
- Act: `click_at_xy(x,y)`, `type_text(s)`, `fill_input(sel, val)`, `press_key(k)`, `scroll(dy)`, `upload_file(sel, path)`
- Escape hatches: `js(expr)` (run JS, returns the value), `cdp(method, **params)`, `http_get(url)`

## Notes

- Read text via `js("document.body.innerText")` or `page_info()`. To read a
  heading: `print(js("document.querySelector('h1')?.innerText"))`.
- Persistent per-user logins survive across messages (the profile is yours).
- Benign headless noise (`SSL handshake failed -100`, `DEPRECATED_ENDPOINT`) is
  harmless — the browser still works. The daemon shows `FAIL`/`0 connections`
  until your first command — that is normal (lazy daemon), not an error.
