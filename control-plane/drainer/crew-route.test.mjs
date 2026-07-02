// Self-check for crew execution rows: a claimed row with crewTaskId is answered by
// Eve, submitted to crew:submitResult, and never routed to orders or channel sends.
//   node control-plane/drainer/crew-route.test.mjs
import assert from "node:assert";
import { extractMemories, processRow } from "./drainer.mjs";

const baseRow = {
  id: "messages:crew-row",
  handle: "crew:crewTasks:1",
  userId: "users:b",
  channel: "telegram",
  replyTarget: "12345",
  userNumber: "12345",
  text: "[crew-задача от Алиса] что у меня в календаре завтра?",
  crewTaskId: "crewTasks:1",
};

// 1. Success path: no order classification, no channel send, submitResult + complete.
{
  const convexCalls = [];
  let classified = 0;
  let sent = 0;
  const deps = {
    classifyOrder: async () => {
      classified++;
      return { is_order: true };
    },
    handleOrder: async () => {
      throw new Error("crew rows must not enter order routing");
    },
    convex: async (kind, path, args) => {
      convexCalls.push({ kind, path, args });
      if (path === "messages:recentForUser") return [];
      return { status: "ok" };
    },
    recallFacts: async () => [],
    callEve: async (_history, _facts, text) => {
      assert.equal(text, baseRow.text, "crew row text is already the full envelope");
      return "[[remember:не отправлять маркер]]ответ агента B";
    },
    extractMemories,
    addFact: () => {},
    rememberRemote: async () => false,
    sendReply: async () => {
      sent++;
    },
    log: () => {},
  };

  await processRow(baseRow, deps);

  assert.equal(classified, 0, "crew rows skip order classification");
  assert.equal(sent, 0, "crew rows do not send to the user's channel");
  assert.deepEqual(
    convexCalls.filter((c) => c.path === "crew:submitResult"),
    [{
      kind: "mutation",
      path: "crew:submitResult",
      args: { taskId: "crewTasks:1", resultText: "ответ агента B" },
    }],
  );
  assert.deepEqual(
    convexCalls.filter((c) => c.path === "messages:complete"),
    [{
      kind: "mutation",
      path: "messages:complete",
      args: { id: "messages:crew-row", reply: "ответ агента B" },
    }],
  );
}

// 2. Eve failure after its internal retry: failTask is called, then the error bubbles
// so the loop's existing catch marks the message row as failed.
{
  const convexCalls = [];
  let classified = 0;
  let sent = 0;
  const deps = {
    classifyOrder: async () => {
      classified++;
      return { is_order: true };
    },
    handleOrder: async () => {
      throw new Error("crew rows must not enter order routing");
    },
    convex: async (kind, path, args) => {
      convexCalls.push({ kind, path, args });
      if (path === "messages:recentForUser") return [];
      return { status: "failed" };
    },
    recallFacts: async () => [],
    callEve: async () => {
      throw new Error("eve stream ended with no answer");
    },
    extractMemories,
    addFact: () => {},
    rememberRemote: async () => false,
    sendReply: async () => {
      sent++;
    },
    log: () => {},
  };

  await assert.rejects(() => processRow(baseRow, deps), /eve stream ended/);

  assert.equal(classified, 0, "failed crew rows still skip order classification");
  assert.equal(sent, 0, "failed crew rows still do not send to channel");
  const failCalls = convexCalls.filter((c) => c.path === "crew:failTask");
  assert.equal(failCalls.length, 1, "Eve failure marks the crew task failed");
  assert.equal(failCalls[0].kind, "mutation");
  assert.equal(failCalls[0].args.taskId, "crewTasks:1");
  assert.ok(/eve stream ended/.test(failCalls[0].args.reason));
  assert.ok(failCalls[0].args.reason.length <= 160, "failure reason is short");
  assert.equal(
    convexCalls.some((c) => c.path === "messages:complete"),
    false,
    "message completion is left to the existing error path",
  );
}

console.log("crew-route self-check PASS");
