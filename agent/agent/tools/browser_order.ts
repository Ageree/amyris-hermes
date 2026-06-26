import { defineTool } from "eve/tools";
import { z } from "zod";

// Contour stub (spec §8). The real engine — browser-use cloud over a CDP endpoint +
// a sticky RU mobile proxy + a per-user profile_id, driving one Yandex flow to the
// "Оплатить" tap — is sub-project #2. Here we only define the tool surface and the
// handoff contract so the agent loop can reason about ordering and the wiring seam
// exists. It performs no browser actions and spends no money.
export default defineTool({
  description:
    "Place a real-world order for the user through an automated browser (taxi, delivery, food, groceries). Describe the intent in natural Russian. Returns a handoff link when a step (SMS code, 3DS, captcha) needs the user.",
  inputSchema: z.object({
    service: z
      .enum(["taxi", "delivery", "food", "grocery"])
      .describe("which service to order from"),
    intent: z.string().min(1).describe("what to order, in natural language"),
    max_amount: z
      .number()
      .positive()
      .optional()
      .describe("spend cap for this order, in rubles (checked against spendPolicy, §9)"),
  }),
  async execute({ service, intent, max_amount }) {
    // ponytail: no browser engine yet — always hand off (ceiling: zero real orders).
    // Upgrade path: open/attach a per-user cloud CDP session, drive the flow, and
    // return handoff_url (live_url) only when an SMS/3DS/captcha step needs the user.
    // TODO(core): wire browser-use cloud CDP + RU proxy (sub-project #2)
    const cap = typeof max_amount === "number" ? `, лимит ${max_amount}₽` : "";
    return {
      status: "needs_handoff" as const,
      summary: `заказ (${service}) пока не автоматизирован: «${intent}»${cap}. браузерный движок появится в sub-project #2.`,
      handoff_url: null,
    };
  },
});
