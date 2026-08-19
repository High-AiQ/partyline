import { beforeEach, describe, expect, it } from "vitest";
import { readOrMintClientId } from "./identity";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("browser socket identity", () => {
  it("survives a reload in session storage without leaking across tabs via local storage", () => {
    const first = readOrMintClientId();

    expect(readOrMintClientId()).toBe(first);
    expect(sessionStorage.getItem("partyline_client_id")).toBe(first);
    expect(localStorage.getItem("partyline_client_id")).toBeNull();
  });
});
