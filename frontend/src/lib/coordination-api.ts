/** REST calls for the coordination features, split from the at-cap core API. */

import { ClaimSchema, OkResultSchema, TaskSchema, TaskStatusSchema } from "./contracts";
import type { Claim, OkResult, Task, TaskStatus } from "./contracts";
import { request } from "./api";

export interface TaskDraft {
  body: string;
  owner: string | null;
}

export interface TaskUpdate {
  body?: string;
  owner?: string | null;
  status?: TaskStatus;
}

export const coordinationApi = {
  claims: (conversationId: string): Promise<Claim[]> =>
    request(`/api/conversations/${conversationId}/claims`, { schema: ClaimSchema.array() }),

  tasks: (conversationId: string): Promise<Task[]> =>
    request(`/api/conversations/${conversationId}/tasks`, { schema: TaskSchema.array() }),

  createTask: (conversationId: string, draft: TaskDraft): Promise<Task> =>
    request(`/api/conversations/${conversationId}/tasks`, {
      schema: TaskSchema,
      method: "POST",
      body: draft,
      fallback: "could not add task",
    }),

  updateTask: (taskId: number, update: TaskUpdate): Promise<Task> =>
    request(`/api/tasks/${String(taskId)}`, {
      schema: TaskSchema,
      method: "PATCH",
      body: {
        ...update,
        ...(update.status === undefined ? {} : { status: TaskStatusSchema.parse(update.status) }),
      },
      fallback: "could not update task",
    }),

  deleteTask: (taskId: number): Promise<OkResult> =>
    request(`/api/tasks/${String(taskId)}`, {
      schema: OkResultSchema,
      method: "DELETE",
      fallback: "could not delete task",
    }),
};
