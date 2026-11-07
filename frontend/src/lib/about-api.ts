/** Read-only facts for the About and Advanced settings sections. */
import { z } from "zod";
import { request } from "./http";

export const AboutSchema = z.object({
  version: z.string(),
  build: z.string(),
  instance_name: z.string().nullable().default(null),
  checkout_path: z.string().nullish(),
  git_head: z.string().nullish(),
});
export type About = z.infer<typeof AboutSchema>;

export const FeatureFlagSchema = z.object({
  name: z.string(),
  enabled: z.boolean(),
  default: z.boolean(),
  status: z.string(),
  summary: z.string(),
});
export type FeatureFlag = z.infer<typeof FeatureFlagSchema>;

export const aboutApi = {
  about: () => request("/api/version", { schema: AboutSchema, fallback: "could not read the version" }),
  features: () =>
    request("/api/features", {
      schema: z.array(FeatureFlagSchema),
      fallback: "could not read feature flags",
    }),
};
