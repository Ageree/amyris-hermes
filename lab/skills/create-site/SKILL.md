---
name: create-site
description: Build and deploy a personalized website or small interactive web app for the user, live at a public URL, from a chat request. Use whenever the user asks you to "make me a site / page / landing / portfolio / link-in-bio" (static) or "make me a guestbook / poll / counter / shared list / wall" (interactive app with saved data). You generate the page, deploy it, and reply with the link.
version: 0.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [sites, web, build, deploy]
---

# Create a site/app in chat (create-site)

The user can ask you to build them a website or a tiny web app, and you publish
it to a live public URL they can open and share. You generate ONE self-contained
HTML document; a publish script deploys it and prints the URL.

## Build it in THIS reply — there is no "later"

Each chat message is ONE shot. There is no background job and no follow-up turn
that quietly finishes the work. If you only say "ok, I'll make it and send it
soon," the user gets NOTHING and waits forever. So when they ask for a site/app,
actually generate the HTML and run the publish script in THIS turn, then reply
with the live URL.

- **Default, don't interrogate.** Fill in the unspecified details yourself (name,
  copy, colors, sections) and ship a solid first version. "на своё усмотрение" /
  "ты решай" / "you decide" means: build it now, ask nothing.
- Ask AT MOST one short question, and only if you genuinely cannot start. Never
  ask twice.
- End every build turn with the exact URL the script printed, and invite tweaks,
  e.g. "вот первая версия: <url> — скажи, что поправить." A change = republish the
  same handle.
- If you won't build something as asked (e.g. a real trademarked brand), say so
  in one line and immediately build the closest version you CAN (a renamed
  concept) — don't stall the thread with refusals.

## Two kinds

- **static** — a personalized page with no saved data: portfolio, landing page,
  link-in-bio, an invite, a résumé, a "happy birthday" page. Pure HTML/CSS/JS.
- **app** — an interactive page that SAVES data shared by everyone who opens it:
  guestbook, poll/voting, hit counter, shared to-do/wishlist, a message wall.
  Each app gets its own private database, provisioned automatically.

If the request needs to remember anything between visits → `app`. Otherwise →
`static`.

## How to build it

1. Generate a SINGLE self-contained HTML file (inline `<style>` and `<script>` —
   no external build, no frameworks needed). Make it genuinely nice and
   personalized to what they asked: real content, good layout, mobile-friendly.
2. Pick a `handle` — a short slug, `a-z 0-9 -`, 2–63 chars (e.g. `annas-bakery`,
   `team-poll`). It becomes part of the URL. If it's taken, publish fails — pick
   another.
3. **For `app` only:** also write the database schema as `CREATE TABLE IF NOT
   EXISTS ...;` statements, and in your HTML use the **already-provided** global
   `dbQuery(sql, args)` — do NOT write your own fetch/DB code. It is injected at
   serve time.

### The `dbQuery` data helper (apps)

`window.dbQuery(sql, args)` is defined for you on the served page. It runs ONE
SQL statement against this app's own database and returns a promise:

```js
// read
const { rows } = await dbQuery("SELECT name, msg FROM guest ORDER BY id DESC", []);
rows.forEach(r => addCard(r.name, r.msg));   // rows = array of {column: value}

// write (always use ? placeholders + args — never string-concat user input)
await dbQuery("INSERT INTO guest(name, msg, ts) VALUES (?, ?, ?)",
              [nameInput.value, msgInput.value, Date.now()]);
```

Return shape: `{ columns: [...], rows: [ {col: value, ...} ], rowsAffected, lastInsertRowid }`.

> ⚠️ v1 apps are PUBLIC: anyone with the link can read AND write the app's data.
> Only build apps where that's fine (guestbook, public poll, shared wall). Do NOT
> build anything that stores private or personal data yet — there is no per-visitor
> login. If the user wants a private app, tell them that's coming soon and offer a
> static page or a public version instead.

## Publish it

Write the files, then run the publish script (its path is in `$SITE_PUBLISH_PY`):

```bash
# write the document
cat > /tmp/site.html <<'HTML'
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>...</title>
<style> /* ... */ </style></head>
<body> ... <script> /* uses dbQuery for apps */ </script></body></html>
HTML

# static:
python3 "$SITE_PUBLISH_PY" --handle annas-bakery --kind static --title "Anna's Bakery" --html-file /tmp/site.html

# app: also write the schema
cat > /tmp/schema.sql <<'SQL'
CREATE TABLE IF NOT EXISTS guest(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, msg TEXT, ts INTEGER);
SQL
python3 "$SITE_PUBLISH_PY" --handle team-guestbook --kind app --title "Team Guestbook" \
  --html-file /tmp/site.html --schema-file /tmp/schema.sql
```

The script prints the live URL on success (e.g.
`https://<deployment>.convex.site/s/team-guestbook`). **Send that exact URL back
to the user.** To change a site later, regenerate the HTML and publish the SAME
handle again — it redeploys in place (the app keeps its data).

## Notes

- Only stdout from the script comes back to you; it prints the URL or an `ERROR:`.
- Keep the document under ~1 MB. One file, everything inline.
- Don't invent the URL — use exactly what the script prints.
