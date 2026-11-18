import { z } from "zod";

export const WorkflowRunsChangedEventSchema = z.object({
  type: z.literal("screen_workflow_runs_changed"),
  conversation_id: z.string(),
});
