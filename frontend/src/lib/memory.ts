import type { Attachment } from "./contracts";

export type MemoryLabelAttachment = Pick<
  Attachment,
  | "memory_usage_bytes"
  | "memory_raw_bytes"
  | "memory_anon_bytes"
  | "memory_file_bytes"
  | "memory_kernel_bytes"
  | "memory_cap_bytes"
>;

const mib = (bytes: number): string => `${String(Math.round(bytes / 1024 ** 2))} MiB`;

/** Explain the working-set meter without hiding the cgroup's raw total or cache. */
export function memoryLabel(attachment: MemoryLabelAttachment): string {
  const usage = attachment.memory_usage_bytes;
  const cap = attachment.memory_cap_bytes;
  if (usage == null || cap == null) return "";
  const workingSet = `${mib(usage)} working set of ${mib(cap)}`;
  const raw = attachment.memory_raw_bytes;
  const anonymous = attachment.memory_anon_bytes;
  const cache = attachment.memory_file_bytes;
  const kernel = attachment.memory_kernel_bytes;
  if (raw != null && anonymous != null && cache != null && kernel != null) {
    return `${mib(raw)} in use (${mib(anonymous)} anonymous + ${mib(kernel)} kernel, ${mib(cache)} file cache, reclaimable); ${workingSet} is non-reclaimable`;
  }
  return raw != null ? `${workingSet} (raw ${mib(raw)})` : workingSet;
}
