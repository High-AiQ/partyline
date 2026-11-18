import { mountDocumentEditor } from "./document-workflow";

export function mountWorkflow(
  root: HTMLElement,
  scenario: string | null,
  schedule = (effect: () => void) => window.setTimeout(effect, 750), // no-poll (b): one save deadline
  interrupt = () => {
    window.alert("Save interrupted");
  },
  trusted = (event: Event) => event.isTrusted,
): void {
  const editor = root.querySelector<HTMLDialogElement>("#record-editor");
  const form = editor?.querySelector("form");
  const notice = root.querySelector<HTMLElement>("#save-status");
  const save = root.querySelector<HTMLButtonElement>("#save");
  if (!editor || !form || !notice || !save) return;
  const disclosure = root.querySelector<HTMLDetailsElement>("#record-lab");
  if (disclosure && (scenario === "ambiguous" || scenario === "delayed" || scenario === "interrupted")) {
    disclosure.open = true;
  }
  if (scenario === "ambiguous") {
    const duplicate = save.cloneNode(true);
    if (duplicate instanceof HTMLElement) duplicate.removeAttribute("id");
    save.after(duplicate);
  }
  root.querySelector("#edit")?.addEventListener("click", (event) => {
    if (!trusted(event) || editor.open) return;
    notice.textContent = "";
    editor.showModal();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!trusted(event) || save.disabled) return;
    if (scenario === "interrupted") {
      interrupt();
      return;
    }
    save.disabled = true;
    const commit = () => {
      notice.dataset.saves = String(Number(notice.dataset.saves) + 1);
      notice.textContent = "Record saved";
      save.disabled = false;
      editor.close();
    };
    if (scenario === "delayed") schedule(commit);
    else commit();
  });
}

const root = document.querySelector("main");
if (root) {
  const scenario = new URLSearchParams(location.search).get("scenario");
  mountWorkflow(root, scenario);
  mountDocumentEditor(root, scenario);
}
