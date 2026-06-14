export const meta = {
  name: 'm4-web-build',
  description: 'Build the M4 web app pages/components + Playwright e2e on the committed Next.js foundation',
  phases: [
    { title: 'Pages', detail: 'landing, signin, dashboard, connect — disjoint file sets, parallel' },
    { title: 'E2E', detail: 'playwright config + spec suite (after pages exist)' },
  ],
}

const ROOT = '/Users/saveliy/Documents/Amyris/web'

const CONTRACT = `
You are building part of a Next.js 15 (App Router) + React 19 + TypeScript + Tailwind v4 web app at ${ROOT}.
The FOUNDATION already exists, is committed, and BUILDS. Do NOT modify foundation files
(package.json, tsconfig.json, next.config.mjs, postcss.config.mjs, app/globals.css, app/layout.tsx,
components/ConvexClientProvider.tsx, middleware.ts, lib/*, components/ui/*). IMPORT from them.

DESIGN SYSTEM (dark "calm terminal", ONE signal-lime accent; lowercase voice everywhere — UI copy,
headings, buttons all lowercase; calm, terse, a little warm; no emoji except an optional single 👋 on success):
- Tailwind v4 utilities from the @theme tokens: bg-canvas bg-surface bg-surface-2 border-border
  text-ink text-muted text-faint text-lime bg-lime text-canvas text-danger. Accent is lime ONLY.
- font-mono (wordmark/code/numbers), font-sans (body). Rounded via rounded-[var(--radius)].
- animation helpers: class "pulse-dot" (breathing dot), class "rise" (entrance).
- UI primitives (USE THESE, do not re-create):
  import { Button } from "@/components/ui/button"      // variant: primary|secondary|ghost|danger, size: sm|md|lg
  import { Card, CardTitle, CardDescription } from "@/components/ui/card"
  import { Badge, StatusDot } from "@/components/ui/badge"   // <StatusDot connected={boolean}/>
- lib helpers:
  import { cn, formatRemaining } from "@/lib/utils"
  import { TIERS } from "@/lib/tiers"                  // [{name,label,priceUsd,msgQuota,channels,blurb,highlight?}]
  import { telegramDeepLink, imessagePairLink, smsPairLink, IMESSAGE_NUMBER, TELEGRAM_BOT_USERNAME } from "@/lib/deeplinks"

CONVEX (all functions EXIST and are deployed to dev). import { api } from "@cp/api":
  query  api.app.account.currentUser ()  -> {_id,email,displayName,name,image,tier,isOperator,createdAt}|null
  query  api.app.channels.myChannels ()  -> [{kind:"imessage"|"telegram",address,verified,lastInboundAt,createdAt}]
  mut    api.app.channels.createPairingToken ({channel}) -> {token,code,expiresAt,channel,deepLink:string|null}
  mut    api.app.channels.disconnectChannel ({channel,address}) -> {ok}
  query  api.app.usage.myUsage ()        -> {tier,status,msgUsed,msgQuota,remaining,unlimited,periodStart,periodEnd}|null
  query  api.app.usage.myUsageTimeline ({limit?}) -> [{at,lane,channel,units}]
  query  api.app.tiers.listTiers ()      -> TierSpec[]
  mut    api.app.tiers.chooseTier ({tier:"free"|"pro"|"max"}) -> {ok,tier,granted,checkoutUrl,message}
  action api.app.upgrade.startCheckout ({tier:"pro"|"max"}) -> {ok,checkoutUrl,message}
Convex React: import { useQuery, useMutation, useAction, Authenticated, Unauthenticated, AuthLoading, useConvexAuth } from "convex/react".
Auth actions: import { useAuthActions } from "@convex-dev/auth/react"  -> const { signIn, signOut } = useAuthActions().
  signIn("google"); signIn("password", formDataOrObj /* {email,password,flow:"signUp"|"signIn"} */);
  signIn("resend-otp", { email });  then verify: signIn("resend-otp", { email, code });

RULES:
- Any component using hooks/handlers/state needs "use client" at the top. app/* pages can be server components
  that render client components, OR mark the page "use client" if simplest.
- Output COMPILING TypeScript/TSX. No new npm deps (no shadcn install, no qrcode pkg). For a QR, you MAY use an
  <img> to https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=<encoded> (degrades gracefully).
- Reactivity: rely on useQuery re-rendering on Convex changes. NEVER poll with setInterval for data.
- Strong typing: no "any" unless unavoidable; handle null/loading states.
- Create ONLY your assigned files. Do not touch foundation or another agent's files.
- After writing, return the list of files you created/replaced.
`

const RET = {
  type: 'object',
  additionalProperties: false,
  properties: {
    files: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['files'],
}

phase('Pages')

const pageSpecs = [
  {
    key: 'landing',
    label: 'pages:landing',
    prompt: `${CONTRACT}

BUILD THE MARKETING LANDING (public, no auth). Files you OWN (create/replace exactly these):
- app/page.tsx                       (REPLACE the temporary stub)
- components/marketing/Nav.tsx       (mono "hermes" wordmark left; right: "sign in" link -> /signin, "get started" Button -> /signin)
- components/marketing/Hero.tsx      (oversized lowercase headline e.g. "your assistant. on imessage & telegram.",
                                      subcopy about a REAL assistant with a REAL browser; primary CTA "get started" -> /signin;
                                      include <BubbleMock/> beside/under it)
- components/marketing/BubbleMock.tsx (a small faux imessage/telegram chat: 2-3 lowercase bubbles, one lime "assistant"
                                      reply; use .rise for entrance; purely decorative, no state needed besides optional CSS)
- components/marketing/TierGrid.tsx  (render the 3 TIERS from "@/lib/tiers" as Cards: label, $price/mo (or "free"),
                                      "<quota> turns / mo", channel badges "imessage" + "telegram"; highlight the pro card;
                                      each card CTA "get started" -> /signin. Make clear BOTH channels are on EVERY tier.)
- components/marketing/Footer.tsx    (tiny: mono wordmark + a lowercase tagline + a muted "lowercase by design" line)
Use Link from "next/link". Keep it elegant, restrained, dark. Headline can be a server component; CTAs are links (no client needed).`,
  },
  {
    key: 'signin',
    label: 'pages:signin',
    prompt: `${CONTRACT}

BUILD THE SIGN-IN PAGE. Files you OWN:
- app/signin/page.tsx                 (centered layout, mono "hermes" wordmark, lowercase "sign in to your assistant", renders <SignInCard/>)
- components/auth/SignInCard.tsx      ("use client"): three ways to sign in, all via useAuthActions():
                                        1) Google: a Button (variant secondary) "continue with google" -> signIn("google")
                                        2) email code: <EmailOtpForm/>
                                        3) password (dev/e2e + fallback): email + password inputs + a "flow" toggle
                                           (sign up / sign in); submit -> signIn("password", { email, password, flow }).
                                        On success, router.push("/connect") (useRouter from "next/navigation").
                                        Show inline error text on a thrown signIn error. data-testid="signin-card".
- components/auth/EmailOtpForm.tsx     ("use client"): step 1 email -> signIn("resend-otp", { email }); step 2 shows a
                                        code input -> signIn("resend-otp", { email, code }); on success router.push("/connect").
                                        Graceful: if step 1 throws (e.g. AUTH_RESEND_KEY unset), show a friendly lowercase
                                        message suggesting google or password instead.
Inputs: style with bg-surface-2 border border-border rounded text-ink px-3 h-10, lime focus ring. All copy lowercase.`,
  },
  {
    key: 'dashboard',
    label: 'pages:dashboard',
    prompt: `${CONTRACT}

BUILD THE DASHBOARD (auth-gated by middleware already). Files you OWN:
- app/dashboard/page.tsx               (renders <DashboardShell/>)
- components/dashboard/DashboardShell.tsx ("use client"): top bar with mono "hermes" + the user's email (from
                                          useQuery(api.app.account.currentUser)) + <SignOutButton/>. Body grid:
                                          <TierCard/>, <UsagePanel/>, <ConnectionsPanel/>. Handle loading (skeleton/“…”)
                                          and the unauth edge (show nothing; middleware handles redirect).
- components/dashboard/TierCard.tsx     ("use client"): current tier (from currentUser.tier / myUsage.tier), its quota,
                                          and upgrade Buttons for higher tiers that call useAction(api.app.upgrade.startCheckout)
                                          ({tier}) and on result show the coming-soon message (a small inline toast/banner,
                                          lowercase). Operator (currentUser.isOperator) shows "max · unlimited", no upgrade.
- components/dashboard/UsagePanel.tsx   ("use client"): useQuery(api.app.usage.myUsage); a lime progress bar of msgUsed/msgQuota
                                          (if unlimited, show "unlimited"); show remaining + period end date. Card.
- components/dashboard/ConnectionsPanel.tsx ("use client"): useQuery(api.app.channels.myChannels). For each binding show the
                                          channel ("imessage"/"telegram"), a masked address, <StatusDot connected={verified}/>,
                                          and a "disconnect" ghost Button -> useMutation(api.app.channels.disconnectChannel)({channel,address}).
                                          If none: a lowercase empty-state + a primary "connect a channel" Button -> /connect.
                                          Always a "connect another" link -> /connect. data-testid="connections-panel".
- components/dashboard/SignOutButton.tsx ("use client"): signOut() from useAuthActions, then router.push("/").
Reactive only (useQuery). Mask phone/chat-id addresses (e.g. keep last 4). Lowercase copy.`,
  },
  {
    key: 'connect',
    label: 'pages:connect',
    prompt: `${CONTRACT}

BUILD THE CONNECT WIZARD (auth-gated). Reactive state machine (design §7), NO polling. Files you OWN:
- app/connect/page.tsx                 (renders <ConnectWizard/>)
- components/connect/ConnectWizard.tsx ("use client"): the state machine:
    step "tier": render TIERS; choosing free -> useMutation(api.app.tiers.chooseTier)({tier:"free"}) then advance;
       choosing pro/max -> chooseTier returns {granted:false, message} -> show the coming-soon message and advance on FREE
       (the user stays free; design §7). Advance to "channel".
    step "channel": two big choices, imessage | telegram -> useMutation(api.app.channels.createPairingToken)({channel})
       stores {token,code,expiresAt,deepLink}; advance to "pair".
    step "pair": render <PairingPanel channel token code expiresAt deepLink/>.
       SUBSCRIBE to useQuery(api.app.channels.myChannels); when a binding for the chosen channel has verified===true,
       advance to "done" (this is the LIVE flip — driven by the webhook bind, no client polling).
    step "done": "you're connected — say hi 👋" + a primary Button/link -> /dashboard.
   Provide a back link and, on the pair step, a "start over" that returns to "channel".
- components/connect/ChannelChoice.tsx ("use client"): the imessage/telegram picker cards.
- components/connect/PairingPanel.tsx  ("use client"): props {channel, token, code, expiresAt, deepLink}.
    telegram: a primary Button/link to deepLink (or telegramDeepLink(TELEGRAM_BOT_USERNAME, token) if deepLink null;
       if no bot username, show the manual "/start <token>" instruction) + <Qr value={deepLink||token}/> + a waiting row
       (<StatusDot connected={false}/> "waiting for you to tap start…").
    imessage: a primary link to imessagePairLink(IMESSAGE_NUMBER, code) ("open messages") + an sms fallback link +
       a big mono <code> chip showing "pair <CODE>" (copyable: a Button "copy" using navigator.clipboard) + waiting row.
    include <Countdown expiresAt={expiresAt}/>; when expired, show a "get a new link" Button (parent re-mints).
    data-testid="pairing-panel"; put the raw token in a data-token attribute / data-testid="pair-token" so e2e can read it.
- components/connect/Qr.tsx            ("use client"): an <img> to the qrserver endpoint with the value encoded; alt text;
                                        graceful if it fails to load.
- components/connect/Countdown.tsx     ("use client"): ticks once/sec via setInterval (UI countdown only — NOT data polling),
                                        renders formatRemaining(expiresAt - Date.now()); cleanup on unmount.
Lowercase copy throughout. Keep one-thing-per-screen.`,
  },
]

const pageResults = await parallel(
  pageSpecs.map((s) => () =>
    agent(s.prompt, { label: s.label, phase: 'Pages', agentType: 'Frontend Developer', schema: RET }),
  ),
)

log(`Pages built: ${pageResults.filter(Boolean).length}/${pageSpecs.length}`)

phase('E2E')

const e2ePrompt = `${CONTRACT}

BUILD THE PLAYWRIGHT E2E SUITE for this app. The pages now exist:
/ (marketing, 3 tiers), /signin (SignInCard with a password form: email+password+flow toggle; data-testid="signin-card"),
/dashboard (data-testid="connections-panel"), /connect (ConnectWizard; pairing panel data-testid="pairing-panel",
the raw pairing token is exposed as data-testid="pair-token").

Environment available to tests (process.env): NEXT_PUBLIC_CONVEX_URL (dev cloud), WORKER_SECRET (for the double-gated
testing:* convex wrappers). The dev deployment has ALLOW_TEST_SEED=1. You can simulate the Telegram bind WITHOUT a real
bot by calling the convex test wrapper from node:
  import { ConvexHttpClient } from "convex/browser";
  const c = new ConvexHttpClient(process.env.NEXT_PUBLIC_CONVEX_URL);
  await c.mutation("testing:testRedeemTelegram", { workerSecret: process.env.WORKER_SECRET, token, address });
(There is also testing:testIssuePairing and testing:testRedeemImessage and testing:cleanupTenants/seedTwoTenants.)

Files you OWN (create exactly these):
- playwright.config.ts   — testDir "./e2e"; use baseURL http://localhost:3000; a webServer that runs "npm run dev"
                           on port 3000 with reuseExistingServer:true and a generous timeout; projects: chromium;
                           fullyParallel false; retries 0 locally. Read env from .env.local automatically (Next does);
                           also forward NEXT_PUBLIC_CONVEX_URL/WORKER_SECRET to tests.
- e2e/helpers.ts         — helpers: uniqueEmail(), signUpViaPassword(page, email, password) (goes to /signin, fills the
                           password form with flow "sign up", submits, waits for /connect or /dashboard),
                           convexClient() (ConvexHttpClient), and a readPairToken(page) helper.
- e2e/auth-gate.spec.ts  — unauthenticated goto /dashboard REDIRECTS to /signin; unauth /connect -> /signin too.
                           (No Convex writes — must be deterministic.)
- e2e/landing.spec.ts    — goto / : asserts the 3 tier labels (free, pro, max) are visible, both channel words
                           ("imessage","telegram") appear, and a "sign in" affordance links to /signin.
- e2e/connect-telegram.spec.ts — sign up a fresh user via password -> /connect -> choose free -> choose telegram ->
                           read the pair token (data-testid="pair-token") -> via convexClient call testing:testRedeemTelegram
                           with a unique address -> ASSERT the wizard flips to the connected/done state REACTIVELY
                           (expect the "you're connected" text WITHOUT any page reload). Tag it so it can be skipped if
                           WORKER_SECRET is absent (test.skip(!process.env.WORKER_SECRET, ...)).
- e2e/isolation.spec.ts  — two fresh users (two browser contexts). Each signs up + binds a telegram address (via the
                           testRedeemTelegram wrapper using each user's own minted token from /connect). Assert that on
                           user A's /dashboard the connections-panel shows A's address and does NOT contain B's address.
                           Skip if WORKER_SECRET absent.
Make every spec robust: explicit waits (expect(...).toBeVisible()), no arbitrary sleeps where avoidable, lowercase-aware
text matchers (use case-insensitive regex or getByText with exact:false). Output COMPILING TypeScript.`

const e2eResult = await agent(e2ePrompt, {
  label: 'e2e:suite',
  phase: 'E2E',
  agentType: 'Frontend Developer',
  schema: RET,
})

log(`E2E suite: ${e2eResult ? (e2eResult.files || []).length + ' files' : 'FAILED'}`)

return {
  pages: pageResults.filter(Boolean).map((r) => ({ files: r.files, notes: r.notes })),
  e2e: e2eResult,
}
