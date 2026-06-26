import { eveChannel } from "eve/channels/eve";
import { httpBasic, localDev, vercelOidc } from "eve/channels/auth";

// The brain is reached server-to-server by our Convex drainer (spec §2.1, Shape A),
// not by a browser. It authenticates with a shared secret via HTTP Basic
// (`httpBasic` compares the password in constant time). EVE_INGRESS_SECRET lives only
// in env (Vercel deploy + Convex), never in code/chat.
// ponytail: one shared secret is enough for one trusted caller (Convex); upgrade path =
// jwtHmac / per-caller creds if we ever expose the agent to more callers.
const ingressSecret = process.env.EVE_INGRESS_SECRET;

export default eveChannel({
  auth: [
    // Open on localhost for `eve dev` and the REPL; ignored in production.
    localDev(),
    // Lets the eve TUI and Vercel deployment-to-deployment calls reach the agent.
    vercelOidc(),
    // Our Convex orchestrator authenticates as user "convex" with the shared secret.
    // If it's unset we omit the entry, so a misconfigured deploy fails CLOSED.
    ...(ingressSecret ? [httpBasic({ username: "convex", password: ingressSecret })] : []),
  ],
});
