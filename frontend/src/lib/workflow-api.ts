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
const PreviewStateSchema = z.enum([
  "not_required",
  "resolved",
  "missing",
  "ambiguous",
  "multiply_matched",
  "unresolved",
]);
const PreviewStepSchema = z.object({
  step: z.string(),
  state: PreviewStateSchema,
  match_count: z.number(),
  ambiguous: z.boolean(),
  multiply_matched: z.boolean(),
  preconditions: z.array(
    z.object({
      state: PreviewStateSchema,
      match_count: z.number(),
      ambiguous: z.boolean(),
      multiply_matched: z.boolean(),
      verdict: z.boolean().nullable(),
    }),
  ),
});
const PreviewSchema = z.object({
  draft_id: z.string(),
  revision: z.string(),
  read_only: z.literal(true),
  steps: z.array(PreviewStepSchema),
});
export type WorkflowPreviewStep = z.infer<typeof PreviewStepSchema>;
export function workflowPreviewIsClean(step: WorkflowPreviewStep): boolean {
  return (
    (step.state === "resolved" || step.state === "not_required") &&
    step.preconditions.every(
      (check) => (check.state === "resolved" || check.state === "not_required") && check.verdict === true,
    )
  );
}
export function workflowPreviewLabel(step: WorkflowPreviewStep): string {
  const count = ` · ${String(step.match_count)} matches`;
  const violated = step.preconditions.filter((check) => check.verdict === false).length;
  const unresolved = step.preconditions.filter(
    (check) =>
      check.verdict === null ||
      (check.state !== "resolved" && check.state !== "not_required" && check.verdict),
  ).length;
  return `${step.state}${count}${violated ? ` · ${String(violated)} precondition${violated === 1 ? "" : "s"} violated` : ""}${unresolved ? ` · ${String(unresolved)} precondition${unresolved === 1 ? "" : "s"} unresolved` : ""}`;
}
const LearningSchema = z.object({
  demonstrations: z.array(
    z.object({
      id: z.string(),
      started_at: z.number(),
      stopped_at: z.number().nullable(),
      state: z.string(),
      calls: z.array(
        z.object({
          index: z.number(),
          at: z.number(),
          operation: z.string(),
          arguments: z.json().nullable(),
          outcome: z.string(),
          observation: z.json().nullable(),
          narration: z.string().nullable(),
          unresolved: z.string().optional(),
        }),
      ),
      narration: z.array(z.object({ index: z.number(), at: z.number().nullable(), text: z.string() })),
    }),
  ),
  drafts: z.array(
    z.object({
      id: z.string(),
      demonstration_id: z.string(),
      name: z.string(),
      revision: z.string(),
      current: z.boolean(),
      approved: z.boolean(),
      bundle: WorkflowReviewSchema.shape.bundle.nullable(),
      alignment: z.record(z.string(), z.number().int()),
      latest_preview: PreviewSchema.nullable(),
    }),
  ),
});
export type WorkflowLearning = z.infer<typeof LearningSchema>;

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
  learning: (line: string) => request(base(line) + "/learning", { schema: LearningSchema }),
  startDemonstration: (line: string, window: string) =>
    request(base(line) + "/demonstrations", {
      schema: z.object({ id: z.string() }),
      method: "POST",
      body: { window },
    }),
  stopDemonstration: (line: string, id: string) =>
    request(`${base(line)}/demonstrations/${encodeURIComponent(id)}/stop`, {
      schema: z.object({ id: z.string(), state: z.string() }),
      method: "POST",
    }),
  narrateDemonstration: (line: string, id: string, text: string) =>
    request(`${base(line)}/demonstrations/${encodeURIComponent(id)}/narration`, {
      schema: z.object({ id: z.string() }),
      method: "POST",
      body: { text },
    }),
  historyDemonstration: (line: string, window: string, start: number, end: number) =>
    request(base(line) + "/demonstrations/from-history", {
      schema: z.object({ id: z.string(), state: z.string() }),
      method: "POST",
      body: { window, start, end },
    }),
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
