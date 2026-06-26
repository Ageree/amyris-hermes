// Calls a WORKER_SECRET-gated Convex function over Convex's function-call HTTP API
// (POST {CONVEX_URL}/api/{mutation|query}, body {path, args, format}). The brain is a
// "worker" (spec §3, invariant A4), so it authenticates by passing workerSecret as an
// argument — never a JWT. Secrets come from process.env only, never hardcoded.

export type ConvexResult =
  | { ok: true; value: unknown }
  | { ok: false; error: string };

export async function convexCall(
  kind: "mutation" | "query",
  path: string,
  args: Record<string, unknown>,
): Promise<ConvexResult> {
  const base = process.env.CONVEX_URL?.replace(/\/+$/, "");
  const secret = process.env.WORKER_SECRET;
  if (!base) return { ok: false, error: "CONVEX_URL not set" };
  if (!secret) return { ok: false, error: "WORKER_SECRET not set" };
  try {
    const res = await fetch(`${base}/api/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        path,
        args: { workerSecret: secret, ...args },
        format: "json",
      }),
    });
    const data = (await res.json().catch(() => null)) as {
      status?: string;
      value?: unknown;
      errorMessage?: string;
    } | null;
    if (!res.ok || data?.status === "error") {
      return {
        ok: false,
        error: data?.errorMessage ?? `convex ${kind} ${path} -> HTTP ${res.status}`,
      };
    }
    return { ok: true, value: data?.value ?? null };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
