export const CREW_TIMEOUT_MS = 20_000;
export const CREW_PERSONAL_CONTAINER_ERROR =
  "crew доступен только в персональном контейнере";
export const CREW_NICKNAME_RE = /^[a-zа-яё0-9_-]{1,32}$/u;

export type CrewApiResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

export interface CrewRuntimeEnv {
  convexUrl: string;
  workerSecret: string;
  userId: string;
}

export interface CrewRuntimeEnvSource {
  CONVEX_URL?: string;
  WORKER_SECRET?: string;
  USER_ID?: string;
}

export interface CrewFunctionRequest {
  url: string;
  method: "POST";
  headers: Record<string, string>;
  body: string;
}

export interface CrewCreateTaskValue {
  taskId: string;
  status: string;
}

export interface CrewLink {
  peerUserId: string;
  nickname: string;
  status: string;
}

interface CrewFunctionRequestInput {
  convexUrl: string | undefined;
  workerSecret: string | undefined;
  kind: "mutation" | "query";
  path: string;
  args: Record<string, unknown>;
}

interface CrewCreateInviteInput {
  convexUrl: string;
  workerSecret: string;
  fromUserId: string;
  contact: string;
  nickname: string;
}

interface CrewCreateTaskInput {
  convexUrl: string;
  workerSecret: string;
  fromUserId: string;
  nickname: string;
  request: string;
}

interface CrewListLinksInput {
  convexUrl: string;
  workerSecret: string;
  userId: string;
}

type FetchLike = typeof fetch;

function cleanEnv(value: string | undefined): string {
  return value?.trim() ?? "";
}

function errorOf(e: unknown): string {
  if (typeof e === "object" && e !== null && "name" in e && e.name === "AbortError") {
    return "convex не ответил за 20 секунд";
  }
  return e instanceof Error ? e.message : String(e);
}

function asConvexBaseUrl(convexUrl: string | undefined): CrewApiResult<string> {
  const base = cleanEnv(convexUrl).replace(/\/+$/u, "");
  if (!base) return { ok: false, error: "CONVEX_URL не задан" };
  return { ok: true, value: base };
}

export function normalizeCrewNickname(nickname: string): string {
  return nickname.trim().toLowerCase();
}

export function isCrewNickname(nickname: string): boolean {
  return CREW_NICKNAME_RE.test(nickname);
}

export function resolveCrewRuntimeEnv(
  env: CrewRuntimeEnvSource,
): CrewApiResult<CrewRuntimeEnv> {
  const userId = cleanEnv(env.USER_ID);
  if (!userId) return { ok: false, error: CREW_PERSONAL_CONTAINER_ERROR };

  const convexUrl = cleanEnv(env.CONVEX_URL);
  if (!convexUrl) return { ok: false, error: "CONVEX_URL не задан" };

  const workerSecret = cleanEnv(env.WORKER_SECRET);
  if (!workerSecret) return { ok: false, error: "WORKER_SECRET не задан" };

  return { ok: true, value: { convexUrl, workerSecret, userId } };
}

export function buildCrewFunctionRequest(
  input: CrewFunctionRequestInput,
): CrewApiResult<CrewFunctionRequest> {
  const base = asConvexBaseUrl(input.convexUrl);
  if (!base.ok) return base;

  const workerSecret = cleanEnv(input.workerSecret);
  if (!workerSecret) return { ok: false, error: "WORKER_SECRET не задан" };

  try {
    return {
      ok: true,
      value: {
        url: `${base.value}/api/${input.kind}`,
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json",
        },
        body: JSON.stringify({
          path: input.path,
          args: { workerSecret, ...input.args },
          format: "json",
        }),
      },
    };
  } catch (e) {
    return { ok: false, error: errorOf(e) };
  }
}

export function buildCrewCreateInviteRequest(
  input: CrewCreateInviteInput,
): CrewApiResult<CrewFunctionRequest> {
  return buildCrewFunctionRequest({
    convexUrl: input.convexUrl,
    workerSecret: input.workerSecret,
    kind: "mutation",
    path: "crew:createInvite",
    args: {
      fromUserId: input.fromUserId,
      contact: input.contact,
      nickname: input.nickname,
    },
  });
}

export function buildCrewCreateTaskRequest(
  input: CrewCreateTaskInput,
): CrewApiResult<CrewFunctionRequest> {
  return buildCrewFunctionRequest({
    convexUrl: input.convexUrl,
    workerSecret: input.workerSecret,
    kind: "mutation",
    path: "crew:createTask",
    args: {
      fromUserId: input.fromUserId,
      nickname: input.nickname,
      request: input.request,
    },
  });
}

export function buildCrewListLinksRequest(
  input: CrewListLinksInput,
): CrewApiResult<CrewFunctionRequest> {
  return buildCrewFunctionRequest({
    convexUrl: input.convexUrl,
    workerSecret: input.workerSecret,
    kind: "query",
    path: "crew:listLinks",
    args: { userId: input.userId },
  });
}

function readConvexPayload(text: string): {
  status?: unknown;
  value?: unknown;
  errorMessage?: unknown;
} | null {
  try {
    const data = JSON.parse(text) as unknown;
    return typeof data === "object" && data !== null ? data : null;
  } catch {
    return null;
  }
}

export async function fetchCrewFunction<T>(
  request: CrewFunctionRequest,
  fetchImpl: FetchLike = fetch,
  timeoutMs = CREW_TIMEOUT_MS,
): Promise<CrewApiResult<T>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetchImpl(request.url, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      signal: controller.signal,
    });
    const text = await res.text();
    const data = readConvexPayload(text);
    const errorMessage =
      typeof data?.errorMessage === "string" ? data.errorMessage : undefined;

    if (!res.ok) {
      return {
        ok: false,
        error: errorMessage ?? `convex HTTP ${res.status}: ${text.slice(0, 300)}`,
      };
    }

    if (data?.status === "error") {
      return { ok: false, error: errorMessage ?? "convex вернул ошибку" };
    }

    if (data?.status !== "success") {
      return { ok: false, error: "convex вернул некорректный ответ" };
    }

    return { ok: true, value: data.value as T };
  } catch (e) {
    return { ok: false, error: errorOf(e) };
  } finally {
    clearTimeout(timeout);
  }
}

export async function createCrewInvite(
  input: CrewCreateInviteInput,
  fetchImpl?: FetchLike,
): Promise<CrewApiResult<unknown>> {
  const request = buildCrewCreateInviteRequest(input);
  if (!request.ok) return request;
  return fetchCrewFunction<unknown>(request.value, fetchImpl);
}

export async function createCrewTask(
  input: CrewCreateTaskInput,
  fetchImpl?: FetchLike,
): Promise<CrewApiResult<CrewCreateTaskValue>> {
  const request = buildCrewCreateTaskRequest(input);
  if (!request.ok) return request;
  return fetchCrewFunction<CrewCreateTaskValue>(request.value, fetchImpl);
}

export async function listCrewLinks(
  input: CrewListLinksInput,
  fetchImpl?: FetchLike,
): Promise<CrewApiResult<CrewLink[]>> {
  const request = buildCrewListLinksRequest(input);
  if (!request.ok) return request;
  return fetchCrewFunction<CrewLink[]>(request.value, fetchImpl);
}
