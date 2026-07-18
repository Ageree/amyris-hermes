# Eve drainer — ACTIVE cutover (Hermes → Eve)

External Node poller that **replaced the Python Hermes worker** as the thing serving the
live message queue. It polls the same live Convex functions the worker used
(`messages:claimNextAny` / `recentForUser` / `complete` / `fail`, worker-secret gated),
routes each row to the deployed Eve agent (`amyris-eve-core.vercel.app`), and sends the
reply over the row's own channel — **iMessage via Sendblue (primary)** or Telegram Bot API.

Chosen over the in-Convex action (`convex/agent.ts`) because the live deployment carries a
`sites` table the worktree schema dropped (→ `apps`), so a Convex push would fail/drop data.
The poller touches **zero** Convex schema/functions — lowest-risk cutover.

## Live deployment (this Mac)

- Code: `~/.eve-drainer/{drainer.mjs,run.sh,eve.env}` (TCC-safe dotfolder; `eve.env` chmod 600).
- launchd: `~/Library/LaunchAgents/com.eve.drainer.plist` (`KeepAlive`, logs in `~/.eve-drainer/`).
- Env: sources `~/.hermes-savedlab/.env` (CONVEX_URL, WORKER_SECRET, SENDBLUE_*, TELEGRAM_BOT_TOKEN)
  + `~/.eve-drainer/eve.env` (EVE_URL, EVE_INGRESS_SECRET).
- Old worker `com.savedcontent.worker` is **stopped + disabled** (plist → `.disabled`).

Deploy after editing source here (`bucloud.mjs` is imported by `drainer.mjs` — always ship both):
```bash
cp control-plane/drainer/{drainer.mjs,bucloud.mjs,run.sh} ~/.eve-drainer/
cp control-plane/drainer/com.eve.drainer.plist ~/Library/LaunchAgents/
launchctl kickstart -k gui/$(id -u)/com.eve.drainer
tail -f ~/.eve-drainer/drainer.log
```

## Per-user cloud browser (browser-use cloud, pay-per-use)

With `BU_CLOUD_API_KEY` set, every order runs in its OWN cloud Chrome bound to that
user's persistent browser-use profile (`bucloud.mjs`): the drainer opens a session
(`openForUser`), `order.py` attaches to its `cdpUrl`, and the session is stopped the
moment the task ends. Billing is **usage-based, no subscription**: BU charges the
session's `timeout` upfront at the PAYG hourly rate and **refunds unused time on stop**
(rounded to the minute) — so `BU_SESSION_TIMEOUT_SEC` is the hard spend cap per task and
a normal ~4-min order costs ~$0.004 at $0.06/h. A login/3DS wall keeps the session
alive instead and the reply carries its `live_url`: the user finishes that step in the
same live browser, the login lands in the persistent profile, and every later order
just runs. Cloud open failure falls back to the local engine automatically.

Env:

| Var | Meaning |
|-----|---------|
| `BU_CLOUD_API_KEY` | browser-use cloud key; setting it turns the cloud engine ON |
| `BU_CLOUD_ENABLED=0` | kill-switch back to the local engine (key stays set) |
| `BU_SESSION_TIMEOUT_SEC` | per-task session cap, default 900 (= max ~$0.015/task upfront, refunded down to actual minutes) |
| `BU_PROFILES_FILE` | userKey→profileId store, default `~/.eve-drainer/bucloud-profiles.json` |
| `BU_PROXY_HOST/PORT/USERNAME/PASSWORD` | BYO RU proxy (mobileproxy.space modem) — required for real Yandex flows; BU has no native RU exit |
| `BU_CLOUD_BASE` | API base override (tests), default `https://api.browser-use.com/api/v2` |

## Rollback to Hermes (instant)
```bash
launchctl bootout gui/$(id -u)/com.eve.drainer
mv ~/Library/LaunchAgents/com.savedcontent.worker.plist.disabled \
   ~/Library/LaunchAgents/com.savedcontent.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.savedcontent.worker.plist
```

Verified live 2026-06-26: synthetic iMessage to +79217818876 → claimed → Eve (M3, lowercase
persona) → Sendblue delivered "привет, eve — я на связи, всё ок, работаем."
