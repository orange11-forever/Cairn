import { z } from "zod";
import type { OperationPreview } from "../../api/projectOperations.ts";

const draftSchema = z.object({
  ownerId: z.string().min(1),
  projectId: z.string().uuid(),
  sourceTask: z.object({ taskId: z.string().uuid(), revision: z.number().int().positive() }),
  assistantId: z.string().uuid().nullable(),
  assistantName: z.string().min(1).max(240),
  task: z.string().min(1).max(25000),
});
export type CodingDispatchDraft = z.infer<typeof draftSchema>;

export function readCodingDispatch(state: unknown, projectId: string, ownerId: string): CodingDispatchDraft | null {
  const parsed = z.object({ codingDispatch: draftSchema }).safeParse(state);
  return parsed.success && parsed.data.codingDispatch.projectId === projectId && parsed.data.codingDispatch.ownerId === ownerId ? parsed.data.codingDispatch : null;
}

export function codingDispatch(preview: OperationPreview, ownerId: string): CodingDispatchDraft | null {
  const action = preview.suggestion.action;
  if (action?.type !== "dispatch_task") return null;
  const task = preview.snapshot.tasks.find(item => item.id === action.taskId);
  if (!task || !action.assistantName) return null;
  return { ownerId, projectId: preview.projectId, sourceTask: { taskId: task.id, revision: task.revision },
    assistantId: action.assistantId, assistantName: action.assistantName,
    task: [`项目任务：${task.title}`, task.description && `任务描述：${task.description}`,
      task.acceptanceCriteria && `验收标准：${task.acceptanceCriteria}`, `本次要求：${preview.intent}`].filter(Boolean).join("\n\n"),
  };
}
