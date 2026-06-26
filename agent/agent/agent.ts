import { defineAgent } from "eve";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";

// Poke-for-Russia brain. Model = MiniMax-M3.
// Default (prod): the gateway id string routes through the Vercel AI Gateway
// (keyless via OIDC) — same model the current fleet runs → zero migration.
// Fallback (local/headless, no Vercel): if MINIMAX_API_KEY is set we call the
// provider directly through an OpenAI-compatible base_url (the lab's OpenRouter
// creds), so the core runs under `eve dev` WITHOUT `eve link`. See docs/eve-core-spec.md §7.
// ponytail: env-switch so the core is runnable before AI Gateway creds are wired;
// drop the branch once `eve link` is done and the gateway path is the only one.
const directKey = process.env.MINIMAX_API_KEY;
const model = directKey
  ? createOpenAICompatible({
      name: "openrouter",
      baseURL: process.env.MINIMAX_BASE_URL ?? "https://openrouter.ai/api/v1",
      apiKey: directKey,
    })(process.env.MINIMAX_MODEL ?? "minimax/minimax-m3")
  : "minimax/minimax-m3";

// Direct (non-gateway) models carry no AI Gateway context-window metadata, so
// compaction needs the size spelled out. M3 = 1M context. (Ignored for the
// gateway string, which the catalog already sizes.)
export default defineAgent(
  directKey ? { model, modelContextWindowTokens: 1_000_000 } : { model },
);
