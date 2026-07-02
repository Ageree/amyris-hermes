type JsonObject = Record<string, unknown>;

const DEFAULT_BASE = "https://api.supermemory.ai";

function baseUrl(): string {
  return (process.env.SUPERMEMORY_BASE_URL || DEFAULT_BASE).replace(/\/+$/, "");
}

function tenantTag(userId: string): string {
  const safe = userId.replace(/[^a-zA-Z0-9_.:-]+/g, "-").slice(0, 96) || "unknown";
  return `hermes:user:${safe}`;
}

async function smFetch(path: string, body: JsonObject): Promise<unknown> {
  const key = process.env.SUPERMEMORY_API_KEY;
  if (!key) throw new Error("SUPERMEMORY_API_KEY not set");
  const res = await fetch(`${baseUrl()}${path}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${key}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(`supermemory ${path} HTTP ${res.status}`);
  return data;
}

function responseItems(data: unknown): unknown[] {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== "object") return [];
  const obj = data as Record<string, unknown>;
  for (const key of ["results", "memories", "documents", "items", "data"]) {
    const val = obj[key];
    if (Array.isArray(val)) return val;
  }
  return [];
}

function itemText(item: unknown): string | null {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return null;
  const obj = item as Record<string, unknown>;
  for (const key of ["memory", "content", "chunk", "text", "summary", "title"]) {
    const val = obj[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  for (const key of ["document", "memory"]) {
    const nested = itemText(obj[key]);
    if (nested) return nested;
  }
  return null;
}

export async function rememberUserMemory(opts: {
  userId: string;
  kind: string;
  key: string;
  value: string;
}): Promise<{ saved: true } | { saved: false; error: string }> {
  const content = `${opts.kind}:${opts.key}: ${opts.value}`.trim();
  const tag = tenantTag(opts.userId);
  const metadata = { kind: opts.kind, key: opts.key, userId: opts.userId };
  for (const [path, body] of [
    ["/v4/memories", { memories: [{ content, metadata }], containerTag: tag }],
    [
      "/v3/documents",
      {
        content,
        containerTag: tag,
        metadata,
        customId: `${opts.userId}:${opts.kind}:${opts.key}`,
      },
    ],
  ] as const) {
    try {
      await smFetch(path, body);
      return { saved: true };
    } catch (e) {
      if (path === "/v3/documents") {
        return { saved: false, error: e instanceof Error ? e.message : String(e) };
      }
    }
  }
  return { saved: false, error: "supermemory write failed" };
}

export async function recallUserMemory(opts: {
  userId: string;
  query?: string;
  kind?: string;
  limit?: number;
}): Promise<{ facts: string[] } | { facts: string[]; error: string }> {
  const body: JsonObject = {
    q: opts.query || opts.kind || "user profile preferences facts",
    limit: opts.limit ?? 8,
    containerTag: tenantTag(opts.userId),
    searchMode: "hybrid",
  };
  if (opts.kind) body.filters = { AND: [{ key: "kind", value: opts.kind }] };
  for (const path of ["/v4/search", "/v3/search"]) {
    try {
      const data = await smFetch(path, body);
      const facts = responseItems(data)
        .map(itemText)
        .filter((v): v is string => Boolean(v))
        .slice(0, opts.limit ?? 8);
      return { facts };
    } catch (e) {
      if (path === "/v3/search") {
        return { facts: [], error: e instanceof Error ? e.message : String(e) };
      }
    }
  }
  return { facts: [], error: "supermemory search failed" };
}
