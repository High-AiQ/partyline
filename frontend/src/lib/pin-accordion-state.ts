const PREFIX = "partyline:pins-collapsed:";

export function pinAccordionStorageKey(conversationId: string): string {
  return `${PREFIX}${conversationId}`;
}

export function storedPinAccordionOpen(conversationId: string): boolean {
  return localStorage.getItem(pinAccordionStorageKey(conversationId)) !== "true";
}

export function storePinAccordionOpen(conversationId: string, open: boolean): void {
  localStorage.setItem(pinAccordionStorageKey(conversationId), String(!open));
}
