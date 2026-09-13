/** Attach-preset traits and lead-scoped staffing — omitted fields use defaults. */

import { z } from "zod";

export const PresetTraitFieldsSchema = z.object({
  reads_images: z.boolean().optional().default(false),
  can_manage: z.boolean().optional().default(false),
  implements: z.boolean().optional().default(true),
});

export const PresetSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    name: z.string(),
    adapter: z.string(),
    command: z.string(),
    created_at: z.number(),
  })
  .extend(PresetTraitFieldsSchema.shape);
export type Preset = z.infer<typeof PresetSchema>;

export const StaffingTraitsSchema = z.object({
  reads_images: z.boolean(),
  can_manage: z.boolean(),
  implements: z.boolean(),
});

export const StaffingPresetSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    name: z.string(),
    adapter: z.string(),
  })
  .extend(StaffingTraitsSchema.shape);

export const StaffingProcessSchema = z.object({
  line_id: z.string(),
  line: z.string(),
  handle: z.string(),
  adapter: z.string(),
  captain: z.boolean(),
  matched_preset: z.object({ id: z.string(), name: z.string(), title: z.string() }).nullable(),
  traits: StaffingTraitsSchema.nullable(),
});

export const StaffingSchema = z.object({
  presets_in_use: z.boolean(),
  presets: z.array(StaffingPresetSchema),
  processes: z.array(StaffingProcessSchema),
});
export type Staffing = z.infer<typeof StaffingSchema>;
