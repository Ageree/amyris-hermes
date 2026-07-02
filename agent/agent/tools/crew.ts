import { defineDynamic, defineTool } from "eve/tools";
import { z } from "zod";
import {
  createCrewInvite,
  createCrewTask,
  CREW_PERSONAL_CONTAINER_ERROR,
  isCrewNickname,
  listCrewLinks,
  normalizeCrewNickname,
  resolveCrewRuntimeEnv,
  type CrewLink,
  type CrewRuntimeEnv,
} from "../lib/crewApi.js";

const nicknameSchema = z
  .string()
  .min(1)
  .max(64)
  .transform(normalizeCrewNickname)
  .refine(isCrewNickname, {
    message: "ник должен быть lowercase: a-z, а-я, ё, 0-9, _ или -, до 32 символов",
  })
  .describe("crew nickname, lowercase /^[a-zа-яё0-9_-]{1,32}$/");

const toolError = (error: string): { error: string } => ({ error });

function crewEnvOrError():
  | { ok: true; value: CrewRuntimeEnv }
  | { ok: false; error: string } {
  return resolveCrewRuntimeEnv(process.env);
}

function statusLabel(status: string): string {
  switch (status) {
    case "active":
      return "активен";
    case "invited":
      return "ждёт подтверждения";
    case "revoked":
      return "отозван";
    default:
      return status;
  }
}

function formatCrewList(links: CrewLink[]): string {
  if (links.length === 0) return "в crew пока никого нет";
  return `crew: ${links
    .map((link) => `${link.nickname} — ${statusLabel(link.status)}`)
    .join("; ")}`;
}

export const crew_add = defineTool({
  description:
    "Добавить человека в crew по контакту и нику. Связь заработает только после подтверждения получателя.",
  inputSchema: z.object({
    contact: z.string().trim().min(1).max(256).describe("phone, iMessage contact, or other contact string"),
    nickname: nicknameSchema,
  }),
  async execute({ contact, nickname }) {
    const env = crewEnvOrError();
    if (!env.ok) return toolError(env.error);

    const result = await createCrewInvite({
      convexUrl: env.value.convexUrl,
      workerSecret: env.value.workerSecret,
      fromUserId: env.value.userId,
      contact,
      nickname,
    });
    if (!result.ok) return toolError(result.error);

    return `инвайт для ${nickname} отправлен, связь появится только после подтверждения`;
  },
});

export const crew_ask = defineTool({
  description:
    "Отправить задачу агенту из crew по нику. Агент получателя выполнит её только если человек подтвердит.",
  inputSchema: z.object({
    nickname: nicknameSchema,
    request: z.string().trim().min(1).max(2000).describe("request for the peer agent, max 2000 chars"),
  }),
  async execute({ nickname, request }) {
    const env = crewEnvOrError();
    if (!env.ok) return toolError(env.error);

    const result = await createCrewTask({
      convexUrl: env.value.convexUrl,
      workerSecret: env.value.workerSecret,
      fromUserId: env.value.userId,
      nickname,
      request,
    });
    if (!result.ok) return toolError(result.error);

    return `задача отправлена агенту ${nickname}, ждём подтверждения`;
  },
});

export const crew_list = defineTool({
  description: "Показать людей и статусы связей в crew пользователя.",
  inputSchema: z.object({}),
  async execute() {
    const env = crewEnvOrError();
    if (!env.ok) return toolError(env.error);

    const result = await listCrewLinks({
      convexUrl: env.value.convexUrl,
      workerSecret: env.value.workerSecret,
      userId: env.value.userId,
    });
    if (!result.ok) return toolError(result.error);

    return formatCrewList(result.value);
  },
});

// Eve names static tools by file path. The three public tools are re-exported
// from crew_add.ts / crew_ask.ts / crew_list.ts; this default keeps crew.ts a
// valid tool-slot module without adding a model-facing "crew" tool.
export default defineDynamic({
  events: {
    "session.started": () => null,
  },
});

export { CREW_PERSONAL_CONTAINER_ERROR };
