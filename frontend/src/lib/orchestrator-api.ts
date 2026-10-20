/** Human captain-style and task-retention controls. */
import { z } from "zod";
import { request } from "./http";
import { ConversationSchema } from "./conversation-contracts";

export const CaptainStyleSchema = z.object({
  captain_mode: z.enum(["manager_tree", "orchestrator"]),
  default_review_policy: z.string().min(1),
});
export type CaptainStyle = z.infer<typeof CaptainStyleSchema>;
export const TaskHistorySettingSchema = z.object({ enabled: z.boolean() });
export type TaskHistorySetting = z.infer<typeof TaskHistorySettingSchema>;

export const RestartedTaskSchema = z.looseObject({ conv_id: z.string() });

export const orchestratorApi = {
  restartReviewer: (taskId: string) =>
    request(`/api/conversations/${taskId}/task/reviewer`, {
      method: "POST",
      schema: RestartedTaskSchema,
      fallback: "could not restart the reviewer",
    }),
  setStyle: (id: string, style: CaptainStyle) =>
    request(`/api/conversations/${id}/captain-style`, {
      method: "PUT",
      body: CaptainStyleSchema.parse(style),
      schema: ConversationSchema,
      fallback: "could not save captain style",
    }),
  history: () => request("/api/settings/auto_clean_task_history", { schema: TaskHistorySettingSchema }),
  setHistory: (enabled: boolean) =>
    request("/api/settings/auto_clean_task_history", {
      method: "PUT",
      body: { enabled },
      schema: TaskHistorySettingSchema,
      fallback: "could not save task history setting",
    }),
};
