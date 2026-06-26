# Served habit-tracker — a personalized Turso-backed app (Feature 5)

A real, usable web app on top of `features/turso_apps/` (provisioner + generator +
libSQL HTTP client). One app == one Turso database. The browser talks only to
`/api/*`; the data-plane token stays server-side.

```
served/
  server.py        stdlib http.server: serves index.html + JSON API, proxies to Turso
  index.html       self-contained page (vanilla JS, no build step), lowercase-RU UI
  provision_app.py provision/delete the app DB via generate_app
  qa/qa_flow.js    Playwright QA: real-user flow, records video + screenshots
  qa/video/        recorded .webm
  qa/shots/        screenshots
```

## API
- `GET  /api/habits` → `{habits:[{id,title,created_at,done_today,checks}]}`
- `POST /api/habits` body `{title}` → 201 `{id,title,done_today,checks}` (title required, non-empty, ≤200)
- `POST /api/habits/{id}/check` → `{id,done_today:true,checks}` (idempotent: ≤1 check/day; id must be +int)

## Run it
```bash
# 1. provision the DB (token written to a chmod-600 file OUTSIDE the repo)
TURSO_TOKEN=<org-token> python3 features/turso_apps/served/provision_app.py \
    --slug qa-habit-tracker --env-out /tmp/app.env

# 2. start the server (token + host come from the env file; never the client)
set -a; source /tmp/app.env; set +a
python3 features/turso_apps/served/server.py --port 8771
# → http://127.0.0.1:8771
```

## QA (records a video)
```bash
APP_URL=http://127.0.0.1:8771 \
NODE_PATH=<dir-with-playwright>/node_modules \
node features/turso_apps/served/qa/qa_flow.js
# → qa/video/*.webm + qa/shots/0{1..4}-*.png ; exits non-zero if persistence fails
```
The QA asserts data survives a full page reload **and** that the page keeps **zero**
`localStorage` keys — so the persisted state can only have come from Turso. Confirm
out-of-band with a direct DB read:
```bash
python3 -c "import sys;sys.path.insert(0,'.');import os;from features.turso_apps import libsql_http;\
print(libsql_http.execute(os.environ['APP_DB_HOST'],os.environ['APP_DB_TOKEN'],'SELECT * FROM habits;'))"
```

## Cleanup
```bash
TURSO_TOKEN=<org-token> python3 features/turso_apps/served/provision_app.py \
    --delete --slug qa-habit-tracker
```

## Not production-ready (known ceilings)
- **No per-user auth on `/api/*`** — single-tenant localhost demo. The real
  multi-tenant serving layer (Convex) gates by signed-in user before reaching a
  store like this. Do not expose off-localhost without that middleware.
- Token is held in process env (correct), but there's no rotation/expiry handling here.
- "done today" uses the server's local-midnight boundary; a multi-timezone product
  would pass the user's tz.
