// Data access + page render for the v1 served-app shape: the habit tracker
// (features/turso_apps/served/server.py + index.html), ported onto the Convex
// serving seam. The httpAction routes in http.ts stay thin — slug resolution +
// auth + JSON envelope — and delegate the SQL/HTML here.
//
// ponytail: v1 hard-codes the habit-tracker shape (the only app the generator
// emits today). Ceiling: a second app shape would need a per-manifest dispatcher
// keyed on apps.tables. Upgrade path: branch render/data on the app's stored
// manifest instead of assuming habits/entries.

import { execute, executeMany } from "./libsql";

export const MAX_TITLE_LEN = 200;

export type Habit = {
  id: number;
  title: string;
  created_at: number;
  done_today: boolean;
  checks: number;
};

export type CheckResult = { id: number; done_today: boolean; checks: number };

// Epoch-ms at the start of "today". ponytail: Convex runs in UTC, so this is the
// UTC day boundary — not the user's local midnight (server.py used the host's local
// tz). Ceiling: cross-tz "done today" can be off by a day. Upgrade: store the user's
// tz on the app row and compute their local midnight.
function todayStartMs(): number {
  const d = new Date();
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

export async function listHabits(host: string, token: string): Promise<Habit[]> {
  const today = todayStartMs();
  const results = await executeMany(host, token, [
    { sql: "SELECT id, title, created_at FROM habits ORDER BY created_at DESC;" },
    {
      sql: "SELECT habit_id, COUNT(*) FROM entries WHERE created_at >= ? GROUP BY habit_id;",
      args: [today],
    },
    { sql: "SELECT habit_id, COUNT(*) FROM entries GROUP BY habit_id;" },
  ]);

  const todayCounts = new Map<number, number>(
    results[1].rows.map((r): [number, number] => [r[0] as number, r[1] as number]),
  );
  const totalCounts = new Map<number, number>(
    results[2].rows.map((r): [number, number] => [r[0] as number, r[1] as number]),
  );

  return results[0].rows.map((row): Habit => {
    const id = row[0] as number;
    return {
      id,
      title: row[1] as string,
      created_at: row[2] as number,
      done_today: (todayCounts.get(id) ?? 0) > 0,
      checks: totalCounts.get(id) ?? 0,
    };
  });
}

export async function addHabit(host: string, token: string, title: string): Promise<Habit> {
  const now = Date.now();
  const res = await execute(
    host,
    token,
    "INSERT INTO habits (title, data, created_at) VALUES (?, ?, ?) RETURNING id;",
    [title, "{}", now],
  );
  const id = res.rows[0][0] as number;
  return { id, title, created_at: now, done_today: false, checks: 0 };
}

// Mark a habit done today (idempotent: at most one entry per day). Returns null when
// the habit doesn't exist (→ 404) so we never insert an orphan entry.
export async function checkToday(
  host: string,
  token: string,
  habitId: number,
): Promise<CheckResult | null> {
  const today = todayStartMs();
  const owner = await execute(host, token, "SELECT id FROM habits WHERE id = ?;", [habitId]);
  if (owner.rows.length === 0) return null;

  const already = await execute(
    host,
    token,
    "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND created_at >= ?;",
    [habitId, today],
  );
  if ((already.rows[0][0] as number) === 0) {
    await execute(
      host,
      token,
      "INSERT INTO entries (habit_id, note, created_at) VALUES (?, ?, ?);",
      [habitId, "done", Date.now()],
    );
  }
  const total = await execute(
    host,
    token,
    "SELECT COUNT(*) FROM entries WHERE habit_id = ?;",
    [habitId],
  );
  return { id: habitId, done_today: true, checks: total.rows[0][0] as number };
}

function escapeHtml(s: string): string {
  const map: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return s.replace(/[&<>"']/g, (c) => map[c]!);
}

// The served page shell — ported verbatim from features/turso_apps/served/index.html,
// with two seams: (1) the title/heading come from the app's `name`; (2) every fetch is
// prefixed with API_BASE = "/app/<slug>" so the page talks ONLY to its own
// /app/<slug>/api/* routes (the data token never reaches the browser). slug is
// validated to a safe charset on apps.register, name is HTML-escaped here.
export function renderAppHtml(slug: string, name: string): string {
  const title = escapeHtml(name);
  const apiBase = JSON.stringify(`/app/${slug}`);
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title}</title>
  <style>
    :root {
      --bg: #f6f5f3;
      --card: #ffffff;
      --ink: #1a1a1a;
      --muted: #8a8a8a;
      --line: #e7e5e1;
      --accent: #2f6f4f;
      --accent-soft: #e6f0ea;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
      -webkit-font-smoothing: antialiased;
    }
    .wrap {
      max-width: 560px;
      margin: 0 auto;
      padding: 56px 20px 80px;
    }
    header h1 {
      font-size: 30px;
      font-weight: 650;
      letter-spacing: -0.02em;
      margin: 0 0 4px;
    }
    header p {
      margin: 0 0 28px;
      color: var(--muted);
      font-size: 15px;
    }
    form {
      display: flex;
      gap: 10px;
      margin-bottom: 26px;
    }
    input[type="text"] {
      flex: 1;
      padding: 13px 15px;
      font-size: 15px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--card);
      outline: none;
      transition: border-color .15s;
    }
    input[type="text"]:focus { border-color: var(--accent); }
    button {
      font-family: inherit;
      cursor: pointer;
      border: none;
      border-radius: 12px;
      font-size: 15px;
    }
    .add-btn {
      padding: 13px 20px;
      background: var(--ink);
      color: #fff;
      font-weight: 550;
    }
    .add-btn:active { transform: translateY(1px); }
    ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
    li {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px 18px;
    }
    .habit-main { min-width: 0; }
    .habit-title { font-size: 16px; font-weight: 550; }
    .habit-meta { font-size: 13px; color: var(--muted); margin-top: 3px; }
    .check-btn {
      flex-shrink: 0;
      padding: 10px 16px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 550;
      white-space: nowrap;
    }
    .check-btn.done {
      background: var(--accent);
      color: #fff;
    }
    .check-btn:disabled { cursor: default; opacity: 1; }
    .empty {
      text-align: center;
      color: var(--muted);
      padding: 40px 0;
      font-size: 15px;
    }
    .err {
      background: #fdecea;
      color: #a3271a;
      border: 1px solid #f4c7bf;
      border-radius: 12px;
      padding: 11px 14px;
      font-size: 14px;
      margin-bottom: 18px;
      display: none;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>${title}</h1>
      <p>отмечай каждый день — данные хранятся в твоей базе</p>
    </header>

    <div class="err" id="err"></div>

    <form id="add-form">
      <input type="text" id="title" placeholder="новая привычка…" autocomplete="off" maxlength="200">
      <button type="submit" class="add-btn">добавить</button>
    </form>

    <ul id="list"></ul>
    <div class="empty" id="empty" hidden>пока пусто. добавь первую привычку выше.</div>
  </div>

  <script>
    const API_BASE = ${apiBase};
    const listEl = document.getElementById("list");
    const emptyEl = document.getElementById("empty");
    const errEl = document.getElementById("err");
    const form = document.getElementById("add-form");
    const titleInput = document.getElementById("title");

    function showError(msg) {
      errEl.textContent = msg;
      errEl.style.display = "block";
    }
    function clearError() { errEl.style.display = "none"; }

    async function api(path, opts) {
      const res = await fetch(API_BASE + path, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || ("ошибка " + res.status));
      return data;
    }

    function render(habits) {
      listEl.innerHTML = "";
      emptyEl.hidden = habits.length > 0;
      for (const h of habits) {
        const li = document.createElement("li");
        li.dataset.id = h.id;

        const main = document.createElement("div");
        main.className = "habit-main";
        const t = document.createElement("div");
        t.className = "habit-title";
        t.textContent = h.title;
        const meta = document.createElement("div");
        meta.className = "habit-meta";
        meta.textContent = h.checks === 0 ? "ещё ни разу" : ("отмечено раз: " + h.checks);
        main.append(t, meta);

        const btn = document.createElement("button");
        btn.className = "check-btn" + (h.done_today ? " done" : "");
        btn.textContent = h.done_today ? "готово ✓" : "готово сегодня";
        btn.disabled = h.done_today;
        btn.addEventListener("click", () => check(h.id, btn));

        li.append(main, btn);
        listEl.append(li);
      }
    }

    async function load() {
      try {
        clearError();
        const data = await api("/api/habits");
        render(data.habits);
      } catch (e) { showError(e.message); }
    }

    async function check(id, btn) {
      try {
        clearError();
        btn.disabled = true;
        await api("/api/habits/" + id + "/check", { method: "POST" });
        await load();
      } catch (e) { showError(e.message); btn.disabled = false; }
    }

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const title = titleInput.value.trim();
      if (!title) return;
      try {
        clearError();
        await api("/api/habits", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        titleInput.value = "";
        await load();
        titleInput.focus();
      } catch (e) { showError(e.message); }
    });

    load();
  </script>
</body>
</html>`;
}
