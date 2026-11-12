import { z } from "zod";

export const GlobalProseSchema = z.object({ value: z.string().nullable() });
export type GlobalProse = z.infer<typeof GlobalProseSchema>;

export const MaxCompactionsSchema = z.object({ value: z.number().int().min(0).max(20) });
export type MaxCompactions = z.infer<typeof MaxCompactionsSchema>;
