import type { ChromeApprovalEvent } from "../lib/chrome-approval-event";

export type ChromeApprovalNotice = ChromeApprovalEvent["notices"][number];

/** Windows waiting on Chrome's own Allow prompt, by the line that owns them. Pushed, never polled. */
class ChromeApprovalState {
  byLine = $state<Record<string, ChromeApprovalNotice[]>>({});

  apply(event: ChromeApprovalEvent): void {
    const others = Object.entries(this.byLine).filter(([convId]) => convId !== event.conv_id);
    this.byLine = Object.fromEntries(
      event.notices.length ? [...others, [event.conv_id, event.notices]] : others,
    );
  }

  forLine(convId: string | undefined): ChromeApprovalNotice[] {
    return convId ? (this.byLine[convId] ?? []) : [];
  }

  reset(): void {
    this.byLine = {};
  }
}

export const chromeApproval = new ChromeApprovalState();
