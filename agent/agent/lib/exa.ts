// Pure request/response shaping for the Exa search REST API (https://docs.exa.ai).
// Ported from features/web_search/exa_search.py. Kept dependency-free and
// side-effect-free so the tool stays serverless-correct and the shaping is
// unit-checkable without a network call (scripts/web_search.check.ts).

export const EXA_SEARCH_URL = "https://api.exa.ai/search";

export interface ExaRequest {
  url: string;
  method: "POST";
  headers: Record<string, string>;
  body: string;
}

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  published: string | null;
}

// Exa caps numResults; clamp to a sane 1..25 like the Python client.
function clampNumResults(n: number): number {
  if (!Number.isFinite(n)) return 5;
  return Math.max(1, Math.min(25, Math.floor(n)));
}

export function buildExaRequest(
  query: string,
  numResults: number,
  apiKey: string,
): ExaRequest {
  const q = query.trim();
  if (!q) throw new Error("query must be a non-empty string");
  return {
    url: EXA_SEARCH_URL,
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
      // Exa accepts the key via the X-API-Key header.
      "x-api-key": apiKey,
    },
    body: JSON.stringify({
      query: q,
      numResults: clampNumResults(numResults),
      type: "auto", // let Exa pick neural vs keyword
      contents: { highlights: { numSentences: 2, highlightsPerUrl: 2 } },
    }),
  };
}

interface ExaRawResult {
  title?: string | null;
  url?: string | null;
  highlights?: unknown;
  text?: unknown;
  publishedDate?: string | null;
}

function snippetOf(r: ExaRawResult): string {
  const hl = r.highlights;
  if (Array.isArray(hl) && hl.length > 0) {
    return hl
      .filter((h): h is string => typeof h === "string" && h.trim() !== "")
      .map((h) => h.trim())
      .join(" ... ");
  }
  if (typeof r.text === "string" && r.text.trim() !== "") {
    return r.text.trim().slice(0, 500);
  }
  return "";
}

export function parseExaResults(data: unknown): SearchResult[] {
  const results = (data as { results?: unknown } | null)?.results;
  if (!Array.isArray(results)) return [];
  const out: SearchResult[] = [];
  for (const raw of results as ExaRawResult[]) {
    const url = typeof raw?.url === "string" ? raw.url : "";
    if (!url) continue; // a result with no URL is useless to the agent
    const title =
      typeof raw.title === "string" && raw.title.trim() !== ""
        ? raw.title.trim()
        : url;
    out.push({
      title,
      url,
      snippet: snippetOf(raw),
      published: typeof raw.publishedDate === "string" ? raw.publishedDate : null,
    });
  }
  return out;
}
