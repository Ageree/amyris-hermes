// Minimal libSQL/Turso HTTP client — a TS port of features/turso_apps/libsql_http.py
// (Hrana-over-HTTP v2 "pipeline" protocol). One POST per batch; the wire format is
// tiny, so a hand-rolled fetch beats pulling in @libsql/client. Pure fetch + web
// globals (atob/btoa) → safe to call from a Convex httpAction.
//
//   POST https://<db-hostname>/v2/pipeline
//   Authorization: Bearer <db-auth-token>
//   body { baton: null, requests: [{type:"execute", stmt:{sql, args}}, …, {type:"close"}] }
//
// ponytail: only the value types this feature uses (null/integer/float/text/blob) are
// encoded/decoded — same scope as the Python reference. Upgrade path: thread a `baton`
// round-trip through executeMany for interactive multi-statement transactions.

export class LibsqlError extends Error {}

const DEFAULT_TIMEOUT_MS = 30_000;

// A Hrana value cell — the on-wire encoding of one SQL argument or result value.
type Cell =
  | { type: "null" }
  | { type: "integer"; value: string }
  | { type: "float"; value: number }
  | { type: "blob"; base64: string }
  | { type: "text"; value: string };

export type Arg = string | number | bigint | boolean | Uint8Array | null | undefined;

// JS has no int/float split, so a whole `number` is encoded as an integer (matching
// the Python `isinstance(int)` branch) — important so `created_at >= ?` / `id = ?`
// compare against INTEGER columns as integers, not REALs.
function encodeArg(v: Arg): Cell {
  if (v === null || v === undefined) return { type: "null" };
  if (typeof v === "boolean") return { type: "integer", value: v ? "1" : "0" };
  if (typeof v === "bigint") return { type: "integer", value: v.toString() };
  if (typeof v === "number") {
    return Number.isInteger(v)
      ? { type: "integer", value: String(v) }
      : { type: "float", value: v };
  }
  if (v instanceof Uint8Array) return { type: "blob", base64: bytesToBase64(v) };
  return { type: "text", value: String(v) };
}

function decodeCell(cell: Cell): unknown {
  switch (cell.type) {
    case "null":
      return null;
    // ponytail ceiling: integers > 2^53 lose precision through Number(); habit ids /
    // epoch-ms timestamps stay well under that. Upgrade: return BigInt for big ints.
    case "integer":
      return Number(cell.value);
    case "float":
      return Number(cell.value);
    case "blob":
      return base64ToBytes(cell.base64);
    default:
      return (cell as { value: string }).value; // text
  }
}

function bytesToBase64(b: Uint8Array): string {
  let s = "";
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s);
}

function base64ToBytes(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export type Stmt = { sql: string; args?: Arg[] };
export type Result = { columns: string[]; rows: unknown[][]; affected: number };

type PipelineReq =
  | { type: "execute"; stmt: { sql: string; want_rows: boolean; args?: Cell[] } }
  | { type: "close" };

// Run statements in order over one pipeline call. Returns one decoded result per
// `execute` (the trailing `close` is skipped). Fails fast on the first error item or
// a non-200 — a half-applied schema must never be reported as success.
export async function executeMany(
  hostname: string,
  token: string,
  statements: Stmt[],
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<Result[]> {
  if (!hostname) throw new Error("hostname is required");
  if (!token) throw new Error("token is required");

  const requests: PipelineReq[] = statements.map((s) => ({
    type: "execute",
    stmt: {
      sql: s.sql,
      want_rows: true,
      ...(s.args && s.args.length ? { args: s.args.map(encodeArg) } : {}),
    },
  }));
  requests.push({ type: "close" });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(`https://${hostname}/v2/pipeline`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify({ baton: null, requests }),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }

  if (!resp.ok) {
    const body = await resp.text();
    throw new LibsqlError(`pipeline HTTP ${resp.status}: ${body.slice(0, 300)}`);
  }

  const body: any = await resp.json();
  const decoded: Result[] = [];
  for (const item of body?.results ?? []) {
    if (item?.type === "error") {
      const err = item.error ?? {};
      throw new LibsqlError(`libsql error: ${err.message ?? JSON.stringify(err)}`);
    }
    const response = item?.response ?? {};
    if (response.type !== "execute") continue; // the trailing close
    const result = response.result ?? {};
    const columns: string[] = (result.cols ?? []).map((c: any) => c?.name);
    const rows: unknown[][] = (result.rows ?? []).map((row: Cell[]) => row.map(decodeCell));
    decoded.push({ columns, rows, affected: result.affected_row_count ?? 0 });
  }
  return decoded;
}

// Convenience: run one statement, return its decoded result.
export async function execute(
  hostname: string,
  token: string,
  sql: string,
  args?: Arg[],
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<Result> {
  const [result] = await executeMany(hostname, token, [{ sql, args }], timeoutMs);
  return result;
}

// Exported only for the offline codec self-check (libsql.selfcheck.ts) — the network
// paths above can't be unit-tested without a live Turso DB, but the value codec can.
export const __codec = { encodeArg, decodeCell };
