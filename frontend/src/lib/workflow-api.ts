import { z } from "zod";
import { OkResultSchema } from "./contracts";
import { request } from "./http";

const WorkflowSummarySchema = z.object({
  name: z.string(),
  description: z.string(),
  use_when: z.string(),
  revision: z.string(),
  approved: z.boolean(),
});
const WorkflowListingSchema = z.union([
  WorkflowSummarySchema,
  z.object({ name: z.string(), error: z.string() }),
]);

const TargetSchema = z.object({
  role: z.string(),
  name: z.json(),
  within: z.json().optional(),
  ordinal: z.number().optional(),
  match_count: z.number().optional(),
});

const ActionSchema = z.object({
  id: z.string(),
  target: TargetSchema,
  action: z.string(),
  confirm: z.boolean(),
  effect: z.string().optional(),
  inputs: z.record(z.string(), z.json()),
  requires: z.array(z.string()),
  preconditions: z.array(z.json()),
  postcondition: z.json(),
  allow_point: z.boolean(),
});
const CallSchema = z.object({
  id: z.string(),
  use: z.union([z.string(), z.object({ by: z.string(), cases: z.record(z.string(), z.string()) })]),
  with: z.record(z.string(), z.json()),
  case_bindings: z.record(z.string(), z.json()),
});
interface RepeatEntry {
  for_each: z.infer<typeof JsonValueSchema>;
  steps: ReviewEntry[];
}
const JsonValueSchema = z.json();
type ReviewEntry = z.infer<typeof ActionSchema> | z.infer<typeof CallSchema> | RepeatEntry;
const ReviewEntrySchema: z.ZodType<ReviewEntry> = z.lazy(() =>
  z.union([
    ActionSchema,
    CallSchema,
    z.object({ for_each: JsonValueSchema, steps: z.array(ReviewEntrySchema) }),
  ]),
);
const ReviewPieceSchema = z.object({
  path: z.string(),
  revision: z.string(),
  definition: z.object({
    description: z.string(),
    parameters: z.record(z.string(), z.json()),
    steps: z.array(ReviewEntrySchema),
  }),
});
const WorkflowReviewSchema = WorkflowSummarySchema.extend({
  bundle: z.object({
    root: z.string(),
    requires: z.array(z.string()),
    pieces: z.record(z.string(), ReviewPieceSchema),
  }),
});

const ConfirmationSchema = z.object({
  token: z.string(),
  effect: z.string(),
  action: z.string(),
  target: TargetSchema,
  inputs: z.record(z.string(), z.json()),
  remaining_seconds: z.number().positive(),
});
const RunSchema = z.object({
  run_id: z.string(),
  workflow: z.string(),
  state: z.enum(["running", "awaiting_confirmation", "stopping", "completed", "failed", "paused", "stopped"]),
  current_step: z.string().nullable(),
  total_steps: z.number().int().positive(),
  verified_steps: z.number().int().nonnegative(),
  resumable: z.boolean(),
  needs_parameters: z.boolean().optional(),
  outcome: z.string().nullable(),
  confirmation: ConfirmationSchema.optional(),
});
export type WorkflowListing = z.infer<typeof WorkflowListingSchema>;
export type WorkflowReview = z.infer<typeof WorkflowReviewSchema>;
export type WorkflowRun = z.infer<typeof RunSchema>;
export type { ReviewEntry };

export const WorkflowParametersSchema = z.record(z.string(), z.json());
type WorkflowParameters = z.infer<typeof WorkflowParametersSchema>;
const base = (line: string) => `/api/conversations/${encodeURIComponent(line)}/screen-workflows`;
const definition = (line: string, name: string) => `${base(line)}/definitions/${encodeURIComponent(name)}`;
const run = (line: string, id: string) => `${base(line)}/runs/${encodeURIComponent(id)}`;

export const workflowApi = {
  list: (line: string) =>
    request(base(line), { schema: z.object({ workflows: z.array(WorkflowListingSchema) }) }),
  review: (line: string, name: string) =>
    request(definition(line, name) + "/review", { schema: WorkflowReviewSchema }),
  approve: (line: string, name: string, revision: string) =>
    request(definition(line, name) + "/approval", {
      schema: WorkflowSummarySchema,
      method: "PUT",
      body: { revision },
    }),
  revoke: (line: string, name: string) =>
    request(definition(line, name) + "/approval", { schema: OkResultSchema, method: "DELETE" }),
  runs: (line: string, signal: AbortSignal) =>
    request(base(line) + "/runs", { schema: z.object({ runs: z.array(RunSchema) }), signal }),
  decide: (line: string, id: string, token: string, allow: boolean) =>
    request(run(line, id) + "/confirmation", {
      schema: OkResultSchema,
      method: "POST",
      body: { token, allow },
    }),
  resume: (line: string, id: string, parameters?: WorkflowParameters) =>
    request(run(line, id) + "/resume", { schema: RunSchema, method: "POST", body: { parameters } }),
};
