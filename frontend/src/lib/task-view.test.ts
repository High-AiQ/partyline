import { describe, expect, it } from "vitest";
import { taskView } from "./task-view";

describe("taskView", () => {
  it("splits a body carrying the done-when convention", () => {
    const view = taskView({
      body: "Cockpit LAN bootstrap: config + arm --server-config, prove 0.0.0.0:8642 restart\nDone when: cockpit restarts with the instance label and dogfood recovery proof.",
      owner: "sol",
    });
    expect(view.summary).toBe(
      "Cockpit LAN bootstrap: config + arm --server-config, prove 0.0.0.0:8642 restart",
    );
    expect(view.doneWhen).toBe("cockpit restarts with the instance label and dogfood recovery proof.");
    expect(view.owner).toBe("sol");
  });

  it("keeps a plain body whole with no expectation", () => {
    const view = taskView({ body: "Revisit GitHub Releases policy", owner: null });
    expect(view.summary).toBe("Revisit GitHub Releases policy");
    expect(view.doneWhen).toBeNull();
    expect(view.owner).toBeNull();
  });

  it("does not misread a summary that merely mentions being done", () => {
    const view = taskView({
      body: "Tasks PATCH accepts completed as done or names valid values",
      owner: null,
    });
    expect(view.doneWhen).toBeNull();
    expect(view.summary).toContain("completed as done");
  });

  it("accepts the colon-optional and case variants agents write", () => {
    const view = taskView({ body: "ship the guard\nDONE WHEN the cap kills a runaway", owner: "opus" });
    expect(view.summary).toBe("ship the guard");
    expect(view.doneWhen).toBe("the cap kills a runaway");
  });

  it("treats an empty expectation as absent rather than an empty chip", () => {
    const view = taskView({ body: "do the thing\nDone when:", owner: null });
    expect(view.doneWhen).toBeNull();
    expect(view.summary).toBe("do the thing");
  });

  it("keeps a multi-line expectation together", () => {
    const view = taskView({
      body: "task\nDone when: first line\nstill the expectation",
      owner: "glm",
    });
    expect(view.doneWhen).toBe("first line\nstill the expectation");
  });
});
