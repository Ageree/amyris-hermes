// Turso (libSQL) provisioning + data access via plain fetch — no npm deps, so it
// runs in the default Convex action runtime. Two surfaces:
//   1. Platform API (api.turso.tech) — create group/database, mint scoped tokens.
//   2. libSQL HTTP `/v2/pipeline` (Hrana over HTTP) on the database host — run SQL.
// Live-verified end-to-end against org "ageree" (2026-06-22): group ensure → db
// create → scoped token → CREATE/INSERT/SELECT via pipeline → delete.

const PLATFORM = "https://api.turso.tech/v1";

export interface TursoConfig {
  platformToken: string;
  org: string;       // organization slug, e.g. "ageree"
  group: string;     // group name, e.g. "sites"
  location: string;  // e.g. "aws-eu-west-1"
}

export interface ProvisionResult {
  dbName: string;
  hostname: string; // <db>-<org>.<region>.turso.io
  token: string;    // scoped full-access JWT for THIS db
}

export interface SqlResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowsAffected: number;
  lastInsertRowid: string | null;
}

export function tursoConfigFromEnv(): TursoConfig {
  const platformToken = process.env.TURSO_PLATFORM_TOKEN ?? "";
  if (!platformToken) throw new Error("TURSO_PLATFORM_TOKEN not configured");
  return {
    platformToken,
    org: process.env.TURSO_ORG ?? "ageree",
    group: process.env.TURSO_GROUP ?? "sites",
    location: process.env.TURSO_LOCATION ?? "aws-eu-west-1",
  };
}

async function platform(
  cfg: TursoConfig,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; json: any }> {
  const res = await fetch(`${PLATFORM}${path}`, {
    method,
    headers: {
      authorization: `Bearer ${cfg.platformToken}`,
      ...(body ? { "content-type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json: any = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  return { status: res.status, json };
}

/** Ensure the group exists (idempotent). Creates it in cfg.location if absent. */
export async function ensureGroup(cfg: TursoConfig): Promise<void> {
  const got = await platform(cfg, "GET", `/organizations/${cfg.org}/groups/${cfg.group}`);
  if (got.status === 200) return;
  const made = await platform(cfg, "POST", `/organizations/${cfg.org}/groups`, {
    name: cfg.group,
    location: cfg.location,
  });
  if (made.status >= 300 && made.status !== 409) {
    throw new Error(`turso group create failed: ${made.status} ${JSON.stringify(made.json)}`);
  }
}

/** Create a database in the group and return its hostname. */
export async function createDatabase(cfg: TursoConfig, name: string): Promise<string> {
  const res = await platform(cfg, "POST", `/organizations/${cfg.org}/databases`, {
    name,
    group: cfg.group,
  });
  if (res.status >= 300) {
    throw new Error(`turso db create failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  const host = res.json?.database?.Hostname ?? res.json?.database?.hostname;
  if (!host) throw new Error(`turso db create: no hostname in response ${JSON.stringify(res.json)}`);
  return host as string;
}

/** Mint a scoped JWT (full-access) for a single database. */
export async function mintToken(cfg: TursoConfig, name: string): Promise<string> {
  const res = await platform(
    cfg,
    "POST",
    `/organizations/${cfg.org}/databases/${name}/auth/tokens?authorization=full-access`,
  );
  if (res.status >= 300) {
    throw new Error(`turso token mint failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
  const jwt = res.json?.jwt;
  if (!jwt) throw new Error("turso token mint: no jwt in response");
  return jwt as string;
}

/** Delete a database (teardown / e2e). Best-effort; throws on hard failure. */
export async function deleteDatabase(cfg: TursoConfig, name: string): Promise<void> {
  const res = await platform(cfg, "DELETE", `/organizations/${cfg.org}/databases/${name}`);
  if (res.status >= 300 && res.status !== 404) {
    throw new Error(`turso db delete failed: ${res.status} ${JSON.stringify(res.json)}`);
  }
}

// ---- data plane: libSQL HTTP /v2/pipeline ----------------------------------

function toArg(value: unknown): { type: string; value?: string } {
  if (value === null || value === undefined) return { type: "null" };
  if (typeof value === "boolean") return { type: "integer", value: value ? "1" : "0" };
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? { type: "integer", value: String(value) }
      : { type: "float", value: String(value) };
  }
  if (typeof value === "bigint") return { type: "integer", value: value.toString() };
  return { type: "text", value: String(value) };
}

function fromCell(cell: any): unknown {
  if (!cell || cell.type === "null") return null;
  if (cell.type === "integer") return Number(cell.value);
  if (cell.type === "float") return Number(cell.value);
  return cell.value; // text / blob (base64)
}

/** Run ONE statement against a database via the libSQL HTTP pipeline. */
export async function execSql(
  hostname: string,
  token: string,
  sql: string,
  args: unknown[] = [],
): Promise<SqlResult> {
  const res = await fetch(`https://${hostname}/v2/pipeline`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({
      requests: [
        { type: "execute", stmt: { sql, args: args.map(toArg) } },
        { type: "close" },
      ],
    }),
  });
  const body: any = await res.json();
  if (res.status >= 300) throw new Error(`libsql HTTP ${res.status}: ${JSON.stringify(body)}`);
  const r0 = body?.results?.[0];
  if (!r0 || r0.type === "error") {
    throw new Error(`libsql error: ${r0?.error?.message ?? JSON.stringify(body)}`);
  }
  const result = r0.response?.result ?? {};
  const columns: string[] = (result.cols ?? []).map((c: any) => c.name);
  const rows: Array<Record<string, unknown>> = (result.rows ?? []).map((row: any[]) => {
    const obj: Record<string, unknown> = {};
    row.forEach((cell, i) => {
      obj[columns[i] ?? String(i)] = fromCell(cell);
    });
    return obj;
  });
  return {
    columns,
    rows,
    rowsAffected: result.affected_row_count ?? 0,
    lastInsertRowid: result.last_insert_rowid ?? null,
  };
}

/** Apply a multi-statement schema (CREATE TABLE ...) to a fresh database. */
export async function applySchema(hostname: string, token: string, schemaSql: string): Promise<void> {
  const stmts = schemaSql
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  for (const stmt of stmts) {
    await execSql(hostname, token, stmt);
  }
}

/** Full provisioning for an app site: group → db → token → schema. */
export async function provisionApp(
  cfg: TursoConfig,
  dbName: string,
  schemaSql: string,
): Promise<ProvisionResult> {
  await ensureGroup(cfg);
  const hostname = await createDatabase(cfg, dbName);
  const token = await mintToken(cfg, dbName);
  if (schemaSql.trim()) await applySchema(hostname, token, schemaSql);
  return { dbName, hostname, token };
}
