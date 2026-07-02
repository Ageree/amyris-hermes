// Network-free unit check for crew Convex request shaping and personal-container
// refusal. Run with Node 24: node scripts/crew.check.ts
import assert from "node:assert/strict";
import {
  buildCrewCreateInviteRequest,
  buildCrewCreateTaskRequest,
  buildCrewListLinksRequest,
  CREW_PERSONAL_CONTAINER_ERROR,
  resolveCrewRuntimeEnv,
  type CrewApiResult,
  type CrewFunctionRequest,
} from "../agent/lib/crewApi.ts";

function mustRequest(result: CrewApiResult<CrewFunctionRequest>): CrewFunctionRequest {
  assert.equal(result.ok, true, result.ok ? undefined : result.error);
  return result.value;
}

const base = {
  convexUrl: "https://convex.example///",
  workerSecret: "worker-secret",
};

const invite = mustRequest(
  buildCrewCreateInviteRequest({
    ...base,
    fromUserId: "user-a",
    contact: "+79990001122",
    nickname: "masha",
  }),
);
assert.equal(invite.url, "https://convex.example/api/mutation");
assert.equal(invite.method, "POST");
assert.equal(invite.headers["content-type"], "application/json");
assert.deepEqual(JSON.parse(invite.body), {
  path: "crew:createInvite",
  args: {
    workerSecret: "worker-secret",
    fromUserId: "user-a",
    contact: "+79990001122",
    nickname: "masha",
  },
  format: "json",
});

const task = mustRequest(
  buildCrewCreateTaskRequest({
    ...base,
    fromUserId: "user-a",
    nickname: "masha",
    request: "спроси, свободна ли она в пятницу",
  }),
);
assert.equal(task.url, "https://convex.example/api/mutation");
assert.deepEqual(JSON.parse(task.body), {
  path: "crew:createTask",
  args: {
    workerSecret: "worker-secret",
    fromUserId: "user-a",
    nickname: "masha",
    request: "спроси, свободна ли она в пятницу",
  },
  format: "json",
});

const list = mustRequest(
  buildCrewListLinksRequest({
    ...base,
    userId: "user-a",
  }),
);
assert.equal(list.url, "https://convex.example/api/query");
assert.deepEqual(JSON.parse(list.body), {
  path: "crew:listLinks",
  args: {
    workerSecret: "worker-secret",
    userId: "user-a",
  },
  format: "json",
});

assert.deepEqual(
  resolveCrewRuntimeEnv({
    CONVEX_URL: "https://convex.example",
    WORKER_SECRET: "worker-secret",
    USER_ID: "",
  }),
  { ok: false, error: CREW_PERSONAL_CONTAINER_ERROR },
);

console.log("crew shaping check: PASS");
