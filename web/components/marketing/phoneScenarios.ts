// Data + pure state-machine for the animated telegram showcase (PhoneShowcase).
// Each scenario is a real, hard request → dhizume browses/works → sends back a
// rich result (a file, a table, a checklist, or a confirmation card). Lowercase
// brand voice. Kept framework-free so the reveal logic is unit-testable.

export type Rich =
  | { kind: "file"; name: string; meta: string }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "checklist"; items: { text: string; done: boolean }[] }
  | { kind: "card"; title: string; lines: string[]; tag: string };

export interface Scenario {
  user: string; // what the person texts
  work: string; // the "doing real work" chip shown while she types
  reply: string; // her text bubble
  rich: Rich; // the attachment she sends back
}

// 10 scenarios of genuinely hard work — writing, applying, booking, buying,
// researching, watching. Each ends in a concrete artifact, not just talk.
export const SCENARIOS: Scenario[] = [
  {
    user: "write my thesis on ai's impact on the job market, ~60 pages",
    work: "researching · 42 sources",
    reply: "done. 61 pages, cited and formatted to your template.",
    rich: { kind: "file", name: "thesis_ai_jobs.docx", meta: "61 pages · 1.2 mb" },
  },
  {
    user: "write a full scientific report on crispr gene editing, with citations",
    work: "reading · 31 papers",
    reply: "done. abstract, methods, results, and 31 references in ieee style.",
    rich: { kind: "file", name: "crispr_report.pdf", meta: "19 pages · 31 refs" },
  },
  {
    user: "i want a new job — find roles, rewrite my résumé, and apply for me",
    work: "applying · linkedin",
    reply: "tailored your résumé to each posting and applied to 9 roles. i'll track the replies.",
    rich: {
      kind: "checklist",
      items: [
        { text: "stripe — applied, résumé tuned", done: true },
        { text: "notion — applied, résumé tuned", done: true },
        { text: "linear — applied, résumé tuned", done: true },
        { text: "+ 6 more · résumé_v3.pdf attached", done: true },
      ],
    },
  },
  {
    user: "find 3 flights to lisbon under $400 next month, hold the cheapest",
    work: "browsing · 6 sites",
    reply: "held the cheapest — tap air, $362, jun 14.",
    rich: {
      kind: "table",
      head: ["airline", "price", "leaves"],
      rows: [
        ["tap air", "$362", "jun 14"],
        ["lufthansa", "$398", "jun 12"],
        ["klm", "$455", "jun 18"],
      ],
    },
  },
  {
    user: "book a table for 4, friday 8pm, somewhere with great reviews",
    work: "booking · opentable",
    reply: "booked. confirmation just hit your inbox.",
    rich: {
      kind: "card",
      title: "lupa · trattoria",
      lines: ["friday 8:00 pm · party of 4", "4.7★ · 0.4 mi away"],
      tag: "confirmed",
    },
  },
  {
    user: "draft an nda for a freelance designer and email it to maria",
    work: "drafting · sending",
    reply: "drafted and sent to maria. signature link included.",
    rich: { kind: "file", name: "nda_freelance.pdf", meta: "3 pages · sent to maria" },
  },
  {
    user: "compare the top robot vacuums under $300 and buy the best one",
    work: "comparing · 11 reviews",
    reply: "roborock q5 won. ordered — arrives thursday.",
    rich: {
      kind: "table",
      head: ["model", "price", "score"],
      rows: [
        ["roborock q5", "$279", "9.1"],
        ["eufy 11s", "$219", "8.3"],
        ["shark ai", "$298", "8.0"],
      ],
    },
  },
  {
    user: "summarize my unread emails and flag anything urgent",
    work: "reading · 23 threads",
    reply: "23 unread. 2 need you today —",
    rich: {
      kind: "checklist",
      items: [
        { text: "lease renewal — reply by 5pm", done: false },
        { text: "invoice #2231 — overdue", done: false },
        { text: "9 newsletters — archived", done: true },
      ],
    },
  },
  {
    user: "make a 10-slide pitch deck for my coffee startup",
    work: "designing · 10 slides",
    reply: "done. brand colors, charts, speaker notes.",
    rich: { kind: "file", name: "brewly_pitch.pdf", meta: "10 slides · 4.6 mb" },
  },
  {
    user: "watch this ps5 listing and grab it the moment it drops under $400",
    work: "watching · live",
    reply: "watching now. i'll check out the instant it dips.",
    rich: {
      kind: "card",
      title: "sony ps5 · slim",
      lines: ["target $400 · now $469", "checks every 5 min"],
      tag: "watching",
    },
  },
  {
    user: "plan a 3-day tokyo trip and book the hotel",
    work: "planning · booking",
    reply: "3-day plan set and the hotel's booked.",
    rich: {
      kind: "card",
      title: "tokyo · 3 days",
      lines: ["day 1 shibuya · day 2 asakusa · day 3 teamlab", "hotel shinjuku · $140/night"],
      tag: "booked",
    },
  },
];

// Reveal steps within one scenario:
//   0 user bubble · 1 typing/working chip · 2 reply text · 3 rich attachment
export const FINAL_STEP = 3;

export interface PlayState {
  idx: number;
  step: number;
}

// Pure transition: walk steps 0→FINAL within a scenario, then wrap to the next
// scenario's step 0 (looping). No timers here so it can be asserted directly.
export function advance(s: PlayState, count: number): PlayState {
  if (s.step < FINAL_STEP) return { idx: s.idx, step: s.step + 1 };
  return { idx: (s.idx + 1) % count, step: 0 };
}

// How long the CURRENT step stays on screen before advancing (ms). The typing
// step lingers (she's "working"); the finished rich answer holds the longest.
export function stepDelay(step: number): number {
  switch (step) {
    case 0:
      return 700; // user message read time → she starts typing
    case 1:
      return 1400; // working/typing
    case 2:
      return 800; // reply text → attachment
    default:
      return 3200; // hold the full answer, then next scenario
  }
}
