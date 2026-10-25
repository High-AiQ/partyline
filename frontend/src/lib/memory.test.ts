import { describe, expect, it } from "vitest";
import { memoryLabel } from "./memory";

const gib = 1024 ** 3;

describe("memoryLabel", () => {
  it("separates the non-reclaimable meter from raw memory and reclaimable cache", () => {
    expect(
      memoryLabel({
        memory_usage_bytes: 2 * gib,
        memory_raw_bytes: 4 * gib,
        memory_anon_bytes: 1.5 * gib,
        memory_file_bytes: 2 * gib,
        memory_kernel_bytes: 0.5 * gib,
        memory_cap_bytes: 8 * gib,
      }),
    ).toBe(
      "4096 MiB in use (1536 MiB anonymous + 512 MiB kernel, 2048 MiB file cache, reclaimable); 2048 MiB working set of 8192 MiB is non-reclaimable",
    );
  });

  it("keeps legacy and incomplete samples readable", () => {
    expect(memoryLabel({ memory_usage_bytes: gib, memory_cap_bytes: 2 * gib })).toBe(
      "1024 MiB working set of 2048 MiB",
    );
    expect(
      memoryLabel({ memory_usage_bytes: gib, memory_raw_bytes: 2 * gib, memory_cap_bytes: 3 * gib }),
    ).toBe("1024 MiB working set of 3072 MiB (raw 2048 MiB)");
    expect(memoryLabel({})).toBe("");
  });
});
