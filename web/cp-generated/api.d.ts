/* eslint-disable */
/**
 * Vendored Convex API stub — for the Vercel build, which roots at `web/` and so
 * cannot see the sibling `control-plane/convex/` source the real generated
 * `api.d.ts` type-imports (`../messages.js`, `../app/account.js`, …).
 *
 * The real `_generated/api.js` is `export const api = anyApi` — there is NO
 * per-function codegen, so a loosely-typed reference is RUNTIME-IDENTICAL. The
 * authoritative backend types are defined and type-checked in `control-plane/`;
 * the web app only ever does `import { api } from "@cp/api"` and passes the
 * references straight into Convex's `useQuery`/`useMutation`, which accept any
 * `FunctionReference`. Keeping this stub `any`-typed trades web-side compile
 * checking of function names for a self-contained, reproducible Vercel build.
 *
 * Paired with `cp-generated/api.js`. Do not add real imports here — that would
 * re-introduce the cross-directory dependency this file exists to remove.
 */
export declare const api: any;
export declare const internal: any;
export declare const components: Record<string, never>;
