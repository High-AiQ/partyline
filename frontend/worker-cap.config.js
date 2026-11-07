import { readFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { join } from "node:path";

const MIB = 1024 ** 2;
const BUDGET = 4 * 1024 * MIB;

// Partyline's memory.max can be an emergency backstop above its 4 GiB budget.
export function vitestMaxWorkers({
  read = readFileSync,
  cpus = availableParallelism(),
  env = process.env,
} = {}) {
  if (env.VITEST_MAX_WORKERS !== undefined) {
    const requested = Number(env.VITEST_MAX_WORKERS);
    if (!Number.isSafeInteger(requested) || requested < 1) {
      throw new Error("VITEST_MAX_WORKERS must be a positive integer");
    }
    return requested;
  }

  try {
    const cgroup = read("/proc/self/cgroup", "utf8")
      .split("\n")
      .find((line) => line.startsWith("0::"))
      ?.slice(3);
    if (cgroup === undefined) return Math.min(4, cpus);
    const value = read(join("/sys/fs/cgroup", cgroup, "memory.max"), "utf8").trim();
    if (!/^\d+$/.test(value) || Number(value) <= 0) return Math.min(4, cpus);
    const limit = Math.min(Number(value), BUDGET);
    return Math.max(1, Math.min(cpus, Math.floor((limit - 1536 * MIB) / (300 * MIB))));
  } catch {
    return Math.min(4, cpus);
  }
}
