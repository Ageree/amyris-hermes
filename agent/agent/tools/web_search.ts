import { defineTool } from "eve/tools";
import { z } from "zod";
import { buildExaRequest, parseExaResults, type SearchResult } from "../lib/exa.js";

// Live web search via Exa. The request/response shaping is in lib/exa.ts so it can
// be unit-checked without a network call; this file is the thin runtime + I/O.
export default defineTool({
  description:
    "Search the live web via Exa. Returns titles, URLs, and short snippets. Use for current facts, prices, news, schedules — anything you don't already know.",
  inputSchema: z.object({
    query: z.string().min(1).describe("what to search for"),
    numResults: z
      .number()
      .int()
      .min(1)
      .max(25)
      .optional()
      .describe("how many results to return (default 5)"),
  }),
  async execute({ query, numResults }) {
    const key = process.env.EXA_API_KEY;
    if (!key) {
      return { query, results: [] as SearchResult[], error: "EXA_API_KEY not set" };
    }
    const req = buildExaRequest(query, numResults ?? 5, key);
    try {
      const res = await fetch(req.url, {
        method: req.method,
        headers: req.headers,
        body: req.body,
      });
      if (!res.ok) {
        const detail = (await res.text().catch(() => "")).slice(0, 300);
        return {
          query,
          results: [] as SearchResult[],
          error: `Exa HTTP ${res.status}: ${detail}`,
        };
      }
      return { query, results: parseExaResults(await res.json()) };
    } catch (e) {
      return {
        query,
        results: [] as SearchResult[],
        error: e instanceof Error ? e.message : String(e),
      };
    }
  },
});
