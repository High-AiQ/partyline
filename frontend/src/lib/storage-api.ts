/** Storage usage and the clearing of regenerable data (people only). */
import { z } from "zod";
import { request } from "./http";

export const StorageCategorySchema = z.object({
  key: z.string(),
  label: z.string(),
  paths: z.array(z.string()),
  bytes: z.number().int().nonnegative(),
  clearable: z.boolean(),
  clearable_bytes: z.number().int().nonnegative(),
  clearable_count: z.number().int().nonnegative(),
  candidates: z.array(z.string()),
  approximate: z.boolean(),
});
export type StorageCategory = z.infer<typeof StorageCategorySchema>;

export const StorageClearResultSchema = z.object({
  removed: z.array(z.string()),
  freed_bytes: z.number().int().nonnegative(),
  skipped: z.array(z.object({ path: z.string(), reason: z.string() })),
});
export type StorageClearResult = z.infer<typeof StorageClearResultSchema>;

export const storageApi = {
  list: () =>
    request("/api/storage", { schema: z.array(StorageCategorySchema), fallback: "could not load storage" }),
  clear: (key: string, convId: string | null) =>
    request(`/api/storage/${key}/clear`, {
      method: "POST",
      body: { conv_id: convId },
      schema: StorageClearResultSchema,
      fallback: "could not clear storage",
    }),
};

export const StoragePathSchema = z.object({
  path: z.string(),
  reason: z.string(),
  size_bytes: z.number().int().nonnegative(),
  remove_anyway_allowed: z.boolean().optional(),
});
export const MirrorRetentionSchema = z.object({
  owner_id: z.string(),
  name: z.string(),
  reason: z.string(),
  count: z.number().int().nonnegative(),
});
export const StorageDetailsSchema = z.object({
  kept: z.array(StoragePathSchema),
  retained_mirrors: z.array(MirrorRetentionSchema).optional(),
  idle_lines: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      idle_since: z.number(),
      size_bytes: z.number().int().nonnegative(),
    }),
  ),
});
export type StorageDetails = z.infer<typeof StorageDetailsSchema>;
export const StorageCleanupSchema = z.object({
  removed: z.array(z.string()),
  freed_bytes: z.number().int().nonnegative(),
  skipped: z.array(StoragePathSchema),
  retained_mirrors: z.array(MirrorRetentionSchema).optional(),
});
export type StorageCleanup = z.infer<typeof StorageCleanupSchema>;

export const storageCleanupApi = {
  details: () =>
    request("/api/storage/details", {
      schema: StorageDetailsSchema,
      fallback: "could not load storage details",
    }),
  cleanup: (removeAnyway: string[] = []) =>
    request("/api/storage/cleanup", {
      method: "POST",
      body: { remove_anyway: removeAnyway },
      schema: StorageCleanupSchema,
      fallback: "could not clean up storage",
    }),
};
