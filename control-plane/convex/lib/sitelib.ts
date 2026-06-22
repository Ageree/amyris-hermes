// Pure helpers for the chat-sites feature. NO Convex imports here so the logic
// (handle validation, SQL guard, HTML runtime injection, URL building) is trivial
// to reason about and is exercised through the real functions by the live e2e.

export const SITE_KINDS = ["static", "app"] as const;
export type SiteKind = (typeof SITE_KINDS)[number];

// Reserved handles — anything that would collide with a route, an asset, or read
// as an official surface. Kept small and explicit.
const RESERVED_HANDLES = new Set([
  "s", "site-data", "api", "app", "apps", "www", "admin", "dashboard",
  "connect", "signin", "sites", "static", "assets", "favicon", "robots",
  "telegram", "sendblue", "auth", "_next", "null", "undefined",
]);

const HANDLE_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/; // DNS-label safe, 1..63, no leading/trailing dash

/**
 * Normalize + validate a public site handle. Lowercases, then enforces a
 * DNS-label-safe slug (so it can later become `<handle>.example.com`), length
 * 2..63, and rejects reserved words. Throws Error on invalid input.
 */
export function validateHandle(raw: string): string {
  const h = String(raw ?? "").trim().toLowerCase();
  if (h.length < 2 || h.length > 63) {
    throw new Error("handle must be 2..63 characters");
  }
  if (!HANDLE_RE.test(h)) {
    throw new Error("handle must be a-z, 0-9, dashes; no leading/trailing dash");
  }
  if (h.includes("--")) {
    throw new Error("handle must not contain consecutive dashes");
  }
  if (RESERVED_HANDLES.has(h)) {
    throw new Error(`handle "${h}" is reserved`);
  }
  return h;
}

const MAX_SQL_LEN = 10_000;

/**
 * Guard a single SQL statement before it reaches a site's OWN isolated Turso DB.
 *
 * Trust model: each `app` site has a dedicated, isolated SQLite database reached
 * only through a scoped token held server-side. The libSQL HTTP `execute`
 * request runs exactly ONE statement (Hrana errors on multi-statement SQL), so
 * stacked-query injection is impossible, and all values are passed as bound args
 * (never string-interpolated). The remaining real escape risk is ATTACH/DETACH
 * (reaching a different database), which we block here.
 *
 * ponytail: v1 data API is open (any page visitor can read/write the site's own
 * DB). Ceiling = blast radius is that single site's database only. Upgrade path =
 * per-visitor write tokens / Convex-auth-gated apps.
 */
export function guardSql(raw: string): string {
  const sql = String(raw ?? "").trim();
  if (!sql) throw new Error("empty SQL");
  if (sql.length > MAX_SQL_LEN) throw new Error("SQL too long");
  if (/\b(attach|detach)\b/i.test(sql)) {
    throw new Error("ATTACH/DETACH not allowed");
  }
  return sql;
}

/** Build the public URL for a site given the serving origin base. */
export function buildSiteUrl(base: string, handle: string): string {
  return `${base.replace(/\/+$/, "")}/s/${handle}`;
}

/**
 * Inject the per-site runtime into generated HTML. For `app` sites this defines
 * `window.__SITE` and an async `dbQuery(sql, args)` helper that POSTs to the
 * same-origin data proxy — so generated client code never holds the DB token.
 * For `static` sites nothing is injected. Inserts right after <head> when
 * present, else prepends.
 */
export function injectRuntime(
  html: string,
  opts: { handle: string; kind: SiteKind; apiBase: string },
): string {
  if (opts.kind !== "app") return html;
  const api = `${opts.apiBase.replace(/\/+$/, "")}/site-data/${opts.handle}`;
  const snippet = `
<script>
window.__SITE = { handle: ${JSON.stringify(opts.handle)}, api: ${JSON.stringify(api)} };
window.dbQuery = async function (sql, args) {
  const r = await fetch(window.__SITE.api, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: sql, args: args || [] }),
  });
  const body = await r.json();
  if (!r.ok || body.error) throw new Error(body.error || ("HTTP " + r.status));
  return body; // { columns: [...], rows: [ {col: value, ...} ], rowsAffected, lastInsertRowid }
};
</script>`;
  const headMatch = html.match(/<head[^>]*>/i);
  if (headMatch && headMatch.index !== undefined) {
    const at = headMatch.index + headMatch[0].length;
    return html.slice(0, at) + snippet + html.slice(at);
  }
  return snippet + html;
}
