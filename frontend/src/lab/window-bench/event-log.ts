export function recordTrustedEvent(log: HTMLElement, event: Event): void {
  const target = event.composedPath().find((item) => item instanceof HTMLElement);
  if (!target || target.id === "event-log" || target.closest("#event-log")) return;
  const item = document.createElement("li");
  item.dataset.isTrusted = String(event.isTrusted);
  item.dataset.eventType = event.type;
  const label = target.getAttribute("aria-label");
  if (label) item.dataset.target = label;
  else if (target.id) item.dataset.target = target.id;
  else if (target.textContent.trim()) item.dataset.target = target.textContent.trim();
  else item.dataset.target = target.tagName;
  item.textContent = `isTrusted=${String(event.isTrusted)} type=${event.type} target=${item.dataset.target}`;
  log.append(item);
  const state = document.querySelector<HTMLElement>("#fixture-state");
  const password = target instanceof HTMLInputElement && target.type === "password";
  const value =
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
      ? target.value
      : target.isContentEditable
        ? target.textContent
        : "";
  if (state) {
    state.textContent = target.closest(".cover")
      ? "state overlay=true"
      : password
        ? "state password=filled"
        : value
          ? `state value=${value}`
          : `state target=${item.dataset.target}`;
  }
  if (target.id === "target" && target instanceof HTMLAnchorElement) {
    sessionStorage.setItem("window-bench-event", item.textContent);
  }
}
