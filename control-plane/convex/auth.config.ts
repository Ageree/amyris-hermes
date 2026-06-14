// Convex Auth JWT issuer config (design §9). The deployment trusts tokens whose
// issuer domain is its own site URL; applicationID "convex" is the audience the
// @convex-dev/auth client uses. CONVEX_SITE_URL is injected by Convex at runtime.
export default {
  providers: [
    {
      domain: process.env.CONVEX_SITE_URL,
      applicationID: "convex",
    },
  ],
};
