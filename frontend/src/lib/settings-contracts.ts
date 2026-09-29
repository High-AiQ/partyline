import { z } from "zod";

export const GlobalProseSchema = z.object({ value: z.string().nullable() });
export type GlobalProse = z.infer<typeof GlobalProseSchema>;
