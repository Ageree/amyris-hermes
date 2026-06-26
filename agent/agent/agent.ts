import { defineAgent } from "eve";

// Poke-for-Russia brain. Model = MiniMax-M3, native on the Vercel AI Gateway
// (keyless via OIDC). Same model the current fleet runs → zero migration. See
// docs/eve-core-spec.md §7.
export default defineAgent({
  model: "minimax/minimax-m3",
});
