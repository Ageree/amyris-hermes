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

Deploy after editing source here:
```bash
cp control-plane/drainer/{drainer.mjs,run.sh} ~/.eve-drainer/
cp control-plane/drainer/com.eve.drainer.plist ~/Library/LaunchAgents/
launchctl kickstart -k gui/$(id -u)/com.eve.drainer
tail -f ~/.eve-drainer/drainer.log
```

## Rollback to Hermes (instant)
```bash
launchctl bootout gui/$(id -u)/com.eve.drainer
mv ~/Library/LaunchAgents/com.savedcontent.worker.plist.disabled \
   ~/Library/LaunchAgents/com.savedcontent.worker.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.savedcontent.worker.plist
```

Verified live 2026-06-26: synthetic iMessage to +79217818876 → claimed → Eve (M3, lowercase
persona) → Sendblue delivered "привет, eve — я на связи, всё ок, работаем."
