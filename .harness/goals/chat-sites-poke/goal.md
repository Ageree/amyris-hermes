# Goal: chat-sites works like Poke

Make the assistant's "build me a site/app in chat" feature (chat-sites) actually
work the way Poke's does: a user texts the assistant a plain request like "сделай
мне лендинг для X" or "сделай гостевую книгу", and the assistant — in ONE reply —
generates a genuinely good, personalized page, deploys it to a live public URL,
and texts back that URL. Interactive apps (guestbook / poll / counter / wall)
must actually save and show data.

Drive this by TESTING IT MYSELF repeatedly through the real Hermes heavy-lane
path (the same path a real inbound iMessage/Telegram message takes on the
operator's live worker), scoring each result, and fixing the skill / routing /
config until it reliably works — not a one-off success, but robust across varied
requests. Keep iterating until an independent audit confirms it behaves like Poke.

## What "like Poke" means here
1. **No interrogation.** A build request produces a built site in that turn, not
   a back-and-forth of clarifying questions. "на своё усмотрение" = build now.
2. **Real deploy.** Every build turn ends with a live `…convex.site/s/<handle>`
   URL that serves HTTP 200.
3. **Genuinely good output.** The page is personalized, has real content + decent
   layout, is mobile-friendly, not a broken/placeholder stub.
4. **Interactive apps work.** A guestbook/poll/counter gets its own Turso DB and
   data round-trips (write persists, reads show it).
5. **Clean reply.** The user receives ONE tidy message with the URL — no diff
   dumps, tool chrome, ANSI, `session_id`, or `⚠️` notices.
6. **Reliable.** The above holds across a battery of varied requests, repeatably.

## Constraints
- Test through the REAL path: `hermes chat --quiet` in HERMES_HOME=`~/.hermes-savedlab`
  with the operator's `.env` sourced, output cleaned by the bridge's regexes —
  this mirrors exactly what the live worker sends to the user. Do NOT spam the
  operator's actual iMessage (no synthetic inbound through Sendblue/Telegram).
- Additive only: don't break existing fast-lane / worker / fleet behavior.
  fast-lane + create-site pytest suites must stay green; the worker must boot clean.
- Apply fixes to BOTH the live operator copies (`~/.hermes-savedlab/worker/`,
  `~/.hermes-savedlab/skills/create-site/`, `~/.hermes-savedlab/config.yaml`) AND
  the repo source (`lab/skeleton/`, `lab/skills/create-site/`) so a future deploy
  carries them.
- Clean up test artifacts (delete probe sites rows + their Turso DBs) so the
  battery doesn't leave junk.
- Push / merge / prod-deploy remain the operator's call (not part of this goal).
