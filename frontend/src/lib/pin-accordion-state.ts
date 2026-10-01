const PREFIX = "partyline:pins-collapsed:";

export function pinAccordionStorageKey(conversationId: string): string {
  return `${PREFIX}${conversationId}`;
}

export function storedPinAccordionOpen(conversationId: string): boolean {
  try {
    return localStorage.getItem(pinAccordionStorageKey(conversationId)) !== "true";
  } catch {
    return true;
  }
}

export function storePinAccordionOpen(conversationId: string, open: boolean): void {
  try {
    localStorage.setItem(pinAccordionStorageKey(conversationId), String(!open));
  } catch {
    // Storage may be blocked; this tab still tracks the in-memory open state.
  }
}
