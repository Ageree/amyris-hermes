import { afterEach, describe, expect, it, vi } from "vitest";
import type { Id } from "../convex/_generated/dataModel";
import {
  assertActiveLink,
  assertFailTaskRunning,
  assertTaskRecipient,
  buildCrewButtons,
  buildCrewEnvelope,
  buildCrewExecutionEnqueueArgs,
  decisionTarget,
  parseCrewDecision,
  scheduleCrewNotify,
  shouldInterceptCrewDecision,
} from "../convex/crew";
import { notifyEnvForChannel } from "../convex/lib/notify";
import { projectClaimedMessage } from "../convex/messages";

const userA = "users:a" as Id<"users">;
const userB = "users:b" as Id<"users">;
const userC = "users:c" as Id<"users">;
const taskId = "crewTasks:1" as Id<"crewTasks">;
const messageId = "messages:1" as Id<"messages">;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("crew contract 1: enqueue to drainer projection", () => {
  it("carries crewTaskId from approveTask enqueue args through claim projection", () => {
    const enqueue = buildCrewExecutionEnqueueArgs({
      taskId,
      toUserId: userB,
      fromName: "Маша",
      request: "свободна ли она в пятницу",
      channel: "telegram",
      replyTarget: "12345",
    });

    expect(enqueue.handle).toBe(`crew:${taskId}`);
    expect(enqueue.crewTaskId).toBe(taskId);
    expect(enqueue.text).toBe(
      buildCrewEnvelope("Маша", "свободна ли она в пятницу"),
    );

    const claimed = projectClaimedMessage({
      _id: messageId,
      ...enqueue,
      userNumber: enqueue.replyTarget,
    });
    expect(claimed.crewTaskId).toBe(taskId);
    expect(claimed.userId).toBe(userB);
    expect(claimed.replyTarget).toBe("12345");
  });
});

describe("crew contract 2: bare yes/no intercept", () => {
  it("routes bare decisions for both phases and falls through otherwise", () => {
    expect(parseCrewDecision("да")).toBe("approve");
    expect(parseCrewDecision("нет")).toBe("decline");
    expect(parseCrewDecision("yes")).toBe("approve");
    expect(parseCrewDecision("no")).toBe("decline");

    expect(shouldInterceptCrewDecision("да", { status: "pending_approval" })).toBe(true);
    expect(decisionTarget("pending_approval", "approve")).toBe("approveTask");
    expect(decisionTarget("pending_approval", "decline")).toBe("declineTask");

    expect(shouldInterceptCrewDecision("да", { status: "result_pending" })).toBe(true);
    expect(decisionTarget("result_pending", "approve")).toBe("approveResult");
    expect(decisionTarget("result_pending", "decline")).toBe("declineResult");

    expect(shouldInterceptCrewDecision("да", null)).toBe(false);
    expect(shouldInterceptCrewDecision("да пойдём", { status: "pending_approval" })).toBe(false);
    expect(parseCrewDecision("да пойдём")).toBeNull();
  });
});

describe("crew contract 3: isolation guards", () => {
  it("rejects missing active links and decisions from the wrong user", () => {
    expect(() => assertActiveLink(null)).toThrow(/active crew link/);
    expect(() => assertActiveLink({ status: "invited" })).toThrow(/active crew link/);
    expect(() => assertActiveLink({ status: "active" })).not.toThrow();

    expect(() => assertTaskRecipient({ toUserId: userB }, userC)).toThrow(
      /unauthorized crew task/,
    );
    expect(() => assertTaskRecipient({ toUserId: userB }, userB)).not.toThrow();
  });
});

describe("crew contract 4: notifications", () => {
  it("schedules notifyUser payloads with Telegram buttons", async () => {
    const calls: Array<{ delay: number; args: unknown }> = [];
    await scheduleCrewNotify(
      {
        scheduler: {
          runAfter: async (delay: number, _ref: unknown, args: unknown) => {
            calls.push({ delay, args });
            return "scheduled";
          },
        },
      } as any,
      {
        userId: userA,
        text: "Отправить Маша: „ответ“? ДА/НЕТ",
        tgButtons: buildCrewButtons(taskId),
      },
    );

    expect(calls).toHaveLength(1);
    expect(calls[0].delay).toBe(0);
    expect(calls[0].args).toEqual({
      userId: userA,
      text: "Отправить Маша: „ответ“? ДА/НЕТ",
      tgButtons: [[
        { text: "✅ Разрешить", callback_data: `crew:a:${taskId}` },
        { text: "❌ Нет", callback_data: `crew:d:${taskId}` },
      ]],
    });
  });

  it("fails loudly when notification env tokens are missing", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => notifyEnvForChannel("telegram", {})).toThrow(
      /TELEGRAM_BOT_TOKEN/,
    );
    expect(() => notifyEnvForChannel("imessage", {})).toThrow(
      /SENDBLUE_API_KEY_ID/,
    );
    expect(spy).toHaveBeenCalledWith("TELEGRAM_BOT_TOKEN not configured");
    expect(spy).toHaveBeenCalledWith(
      "SENDBLUE_API_KEY_ID / SENDBLUE_API_SECRET_KEY / SENDBLUE_FROM_NUMBER not configured",
    );
  });
});

describe("crew contract 5: Russian regex", () => {
  it("matches bare Cyrillic yes/no without ASCII word-boundary semantics", () => {
    expect(parseCrewDecision("ДА")).toBe("approve");
    expect(parseCrewDecision("да")).toBe("approve");
    expect(parseCrewDecision("НЕТ")).toBe("decline");
    expect(parseCrewDecision("нет")).toBe("decline");
    expect(parseCrewDecision("нет!")).toBeNull();
    expect(parseCrewDecision("ну да")).toBeNull();
  });
});

describe("crew contract 6: failTask transition", () => {
  it("allows only running tasks to be failed by the worker backstop", () => {
    expect(() => assertFailTaskRunning({ status: "running" })).not.toThrow();
    expect(() => assertFailTaskRunning({ status: "result_pending" })).toThrow(
      /crew task is not running: result_pending/,
    );
  });
});
