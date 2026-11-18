import { expect, test } from "vitest";
import page from "../../../lab/window-bench/workflow.html?raw";
import { mountDocumentEditor } from "./document-workflow";

function mount() {
  const root = new DOMParser().parseFromString(page, "text/html").querySelector("main");
  if (!root) throw new Error("fixture missing");
  for (const dialog of root.querySelectorAll("dialog")) {
    dialog.showModal = () => (dialog.open = true);
    dialog.close = () => (dialog.open = false);
  }
  mountDocumentEditor(root, "publication-lock");
  const find = <T extends HTMLElement>(selector: string, kind: new () => T) => {
    const field = root.querySelector(selector);
    if (!(field instanceof kind)) throw new Error(`fixture missing ${selector}`);
    return field;
  };
  return { root, find };
}

test("a comparison row reveals an independent text box only for its Text option", () => {
  const { find } = mount();
  find("#add-table", HTMLElement).click();
  find("#add-row", HTMLElement).click();
  find("#add-row", HTMLElement).click();
  const option = find("#row-2-option-1", HTMLSelectElement);
  const text = find("#row-2-option-1-text", HTMLInputElement);
  expect(text.hidden).toBe(true);
  option.value = "text";
  option.dispatchEvent(new Event("change"));
  expect(text.hidden).toBe(false);
  expect(find("#row-1-option-1-text", HTMLElement).hidden).toBe(true);
  text.value = "Seasonal";
  option.value = "included";
  option.dispatchEvent(new Event("change"));
  expect(text.hidden).toBe(true);
  expect(text.value).toBe("");
});

test("image attachment, text entry and the publish lock keep draft and publication separate", () => {
  const { find } = mount();
  const editor = find("#module-editor", HTMLDialogElement);
  const fileDialog = find("#image-dialog", HTMLDialogElement);
  expect(find("#publish-ready", HTMLElement).hidden).toBe(true);
  find("#add-image", HTMLElement).click();
  find("#choose-image", HTMLElement).click();
  expect(fileDialog.open).toBe(true);
  find("#use-image", HTMLElement).click();
  expect(fileDialog.open).toBe(true);
  const input = find("#module-image", HTMLInputElement);
  const attachment = new File(["image"], "meadow.png", { type: "image/png" });
  Object.defineProperty(input, "files", {
    configurable: true,
    value: [attachment],
  });
  find("#use-image", HTMLElement).click();
  expect(fileDialog.open).toBe(false);
  find("#module-alt", HTMLInputElement).value = "A meadow";
  find("#module-fields", HTMLElement).dispatchEvent(new Event("submit", { cancelable: true }));
  expect(editor.open).toBe(false);
  expect(find("#saved-modules", HTMLElement).textContent).toContain("Image · meadow.png · A meadow");

  find("#add-text", HTMLElement).click();
  find("#module-headline", HTMLInputElement).value = "Field notes";
  find("#module-body", HTMLTextAreaElement).value = "Three routes surveyed.";
  find("#module-fields", HTMLElement).dispatchEvent(new Event("submit", { cancelable: true }));
  expect(find("#saved-modules", HTMLElement).textContent).toContain(
    "Text · Field notes · Three routes surveyed.",
  );
  const lock = find("#block-publishing", HTMLInputElement);
  lock.click();
  expect(find("#publish-ready", HTMLElement).hidden).toBe(true);
  const status = find("#publish-status", HTMLElement);
  find("#publish", HTMLElement).click();
  expect(status.dataset.publishes).toBe("0");
  lock.click();
  expect(find("#publish-ready", HTMLElement).hidden).toBe(false);
  find("#publish", HTMLElement).click();
  find("#publish", HTMLElement).click();
  expect(status.dataset.publishes).toBe("1");
  expect(status.textContent).toBe("Document published");
});
