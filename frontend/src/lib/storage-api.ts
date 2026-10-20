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
