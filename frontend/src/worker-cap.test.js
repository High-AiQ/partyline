import { describe, expect, it } from "vitest";
import { vitestMaxWorkers } from "../worker-cap.config.js";

function reader(limit) {
  return (path) => {
    if (path === "/proc/self/cgroup") return "1:name:/old\n0::/user.slice/test.scope\n";
    expect(path).toBe("/sys/fs/cgroup/user.slice/test.scope/memory.max");
    if (limit === null) throw new Error("missing");
    return limit;
  };
}

describe("vitest worker cap", () => {
  it("uses a modest fallback for an unlimited or missing cgroup", () => {
    expect(vitestMaxWorkers({ read: reader("max\n"), cpus: 32, env: {} })).toBe(4);
    expect(vitestMaxWorkers({ read: reader(null), cpus: 2, env: {} })).toBe(2);
  });

  it("sizes a finite limit with headroom and clamps it to CPUs and the 4 GiB budget", () => {
    expect(vitestMaxWorkers({ read: reader(String(4 * 1024 ** 3)), cpus: 32, env: {} })).toBe(8);
    expect(vitestMaxWorkers({ read: reader(String(6 * 1024 ** 3)), cpus: 32, env: {} })).toBe(8);
    expect(vitestMaxWorkers({ read: reader(String(4 * 1024 ** 3)), cpus: 2, env: {} })).toBe(2);
    expect(vitestMaxWorkers({ read: reader(String(1024 ** 3)), cpus: 32, env: {} })).toBe(1);
  });

  it("honors an explicit environment override", () => {
    expect(vitestMaxWorkers({ read: reader(null), cpus: 2, env: { VITEST_MAX_WORKERS: "7" } })).toBe(7);
  });
});
