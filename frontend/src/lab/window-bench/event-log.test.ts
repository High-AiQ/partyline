import { beforeEach, describe, expect, it } from "vitest";
import { fixtureMarkup, fixtureNames } from "./fixtures";
import { recordTrustedEvent } from "./event-log";

describe("window bench trusted event logs", () => {
  beforeEach(() => {
    document.body.replaceChildren();
  });

  it.each(fixtureNames)("records trust, type and target fields for %s", (name) => {
    document.body.innerHTML = fixtureMarkup(name);
    const log = document.querySelector<HTMLElement>("#event-log");
    if (!log) throw new Error("event log missing");
    const button = document.createElement("button");
    button.id = "test-target";
    button.textContent = "Test target";
    button.addEventListener("click", (event) => {
      recordTrustedEvent(log, event);
    });
    document.body.append(button);
    const event = new Event("click", { bubbles: true, composed: true });
    button.dispatchEvent(event);
    expect(event.isTrusted).toBe(false);
    const entry = log.querySelector("li");
    expect(entry?.dataset).toMatchObject({ isTrusted: "false", eventType: "click", target: "test-target" });
    expect(entry?.textContent).toBe("isTrusted=false type=click target=test-target");
  });
});
