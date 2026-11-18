const MAX_COLUMNS = 6;
const MAX_ROWS = 10;
const MODULES = { image: "Image", text: "Text", table: "Comparison table" };

type ElementClass<T extends HTMLElement> = new () => T;

function find<T extends HTMLElement>(root: ParentNode, selector: string, kind: ElementClass<T>): T {
  const node = root.querySelector(selector);
  if (!(node instanceof kind)) throw new Error(`Missing lab fixture element ${selector}`);
  return node;
}

function appendRow(body: HTMLTableSectionElement): void {
  if (body.rows.length >= MAX_ROWS) return;
  const row = body.insertRow();
  row.id = `row-${String(body.rows.length)}`;
  row.setAttribute("aria-label", `Row ${String(body.rows.length)}`);
  const reference = document.createElement("input");
  reference.id = `${row.id}-reference`;
  reference.setAttribute("aria-label", "Reference");
  row.insertCell().append(reference);
  for (let column = 1; column < MAX_COLUMNS; column++) {
    const cell = row.insertCell();
    const select = document.createElement("select");
    select.id = `${row.id}-option-${String(column)}`;
    select.setAttribute("aria-label", `Option ${String(column)}`);
    for (const [label, value] of [
      ["Choose…", ""],
      ["Included", "included"],
      ["Excluded", "excluded"],
      ["Text", "text"],
    ]) {
      select.add(new Option(label, value));
    }
    const text = document.createElement("input");
    text.id = `${select.id}-text`;
    text.setAttribute("aria-label", `Option ${String(column)} text`);
    text.hidden = true;
    select.addEventListener("change", () => {
      text.hidden = select.value !== "text";
      if (text.hidden) text.value = "";
    });
    cell.append(select, text);
  }
}

export function mountDocumentEditor(root: HTMLElement, scenario: string | null): void {
  const editor = find(root, "#module-editor", HTMLDialogElement);
  const files = find(root, "#image-dialog", HTMLDialogElement);
  const image = find(files, "#module-image", HTMLInputElement);
  const form = find(editor, "#module-fields", HTMLFormElement);
  const saved = find(root, "#saved-modules", HTMLOListElement);
  const publish = find(root, "#publish", HTMLButtonElement);
  const status = find(root, "#publish-status", HTMLElement);
  const ready = find(root, "#publish-ready", HTMLElement);
  const block = find(root, "#block-publishing", HTMLInputElement);
  let active: keyof typeof MODULES | undefined;

  function updateReadiness(): void {
    ready.hidden = saved.children.length === 0 || block.checked || publish.disabled;
  }

  function clone(template: string): DocumentFragment {
    return find(root, template, HTMLTemplateElement).content.cloneNode(true) as DocumentFragment;
  }

  find(root, "#failure-control", HTMLElement).hidden = scenario !== "publication-lock";
  block.addEventListener("change", updateReadiness);
  for (const kind of ["image", "text", "table"] as const) {
    find(root, `[data-module="${kind}"]`, HTMLButtonElement).addEventListener("click", () => {
      if (editor.open || publish.disabled) return;
      active = kind;
      find(editor, "#module-kind", HTMLElement).textContent = MODULES[kind];
      image.value = "";
      form.replaceChildren(clone(`#${kind}-fields`), clone("#module-save"));
      form.querySelector("#choose-image")?.addEventListener("click", () => {
        files.showModal();
      });
      form.querySelector("#add-row")?.addEventListener("click", () => {
        appendRow(find(form, "tbody", HTMLTableSectionElement));
      });
      editor.showModal();
    });
  }

  find(files, "#use-image", HTMLButtonElement).addEventListener("click", () => {
    if (!image.files?.length) return;
    find(form, "#chosen-image", HTMLOutputElement).textContent = image.files[0]?.name ?? "";
    files.close();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!active) return;
    const fields = [
      ...form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        "input:not([hidden]), select, textarea, output",
      ),
    ];
    const parts = fields.map((field) => field.value).filter(Boolean);
    const item = document.createElement("li");
    item.textContent = [MODULES[active], ...parts].join(" · ");
    saved.append(item);
    editor.close();
    active = undefined;
    updateReadiness();
  });

  publish.addEventListener("click", () => {
    if (ready.hidden || editor.open) return;
    publish.disabled = true;
    status.dataset.publishes = String(Number(status.dataset.publishes) + 1);
    status.textContent = "Document published";
    updateReadiness();
  });
}
