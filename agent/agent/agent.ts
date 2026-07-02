import { defineAgent } from "eve";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";

// Poke-for-Russia brain. Model = MiniMax-M3.
// The fleet is self-hosted and must never route through Vercel AI Gateway. Keep
// this source-backed so eve reloads the authored model at runtime, while the
// secret itself is read by the fetch wrapper for each provider request.
function getRuntimeMinimaxApiKey() {
  const key = process.env.MINIMAX_API_KEY?.trim();
  if (!key) {
    throw new Error(
      "MINIMAX_API_KEY is required at runtime for the Eve direct OpenRouter model.",
    );
  }
  return key;
}

const openRouterFetch: typeof fetch = async (input, init) => {
  const headers = new Headers(
    input instanceof Request ? input.headers : undefined,
  );

  new Headers(init?.headers).forEach((value, key) => {
    headers.set(key, value);
  });

  headers.set("Authorization", `Bearer ${getRuntimeMinimaxApiKey()}`);
  return fetch(input, { ...init, headers });
};

const model = createOpenAICompatible({
  name: "openrouter",
  baseURL: process.env.MINIMAX_BASE_URL ?? "https://openrouter.ai/api/v1",
  fetch: openRouterFetch,
})(process.env.MINIMAX_MODEL ?? "minimax/minimax-m3");

// Direct (non-gateway) models carry no AI Gateway context-window metadata, so
// compaction needs the size spelled out. M3 = 1M context. (Ignored for the
// gateway string, which the catalog already sizes.)
export default defineAgent({ model, modelContextWindowTokens: 1_000_000 });
