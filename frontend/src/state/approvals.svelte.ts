/** Pending person-approvals across the open line's subtree, mirrored for every tab. */
import type { ApprovalItem } from "../lib/approvals-api";
import { approvalsApi } from "../lib/approvals-api";

export class ApprovalsState {
  items = $state<ApprovalItem[]>([]);
  deciding = $state(false);
  #activeConvId: string | null = null;
  #loadedConvId: string | null = null;
  #generation = 0;

  activate(convId: string): void {
    if (this.#activeConvId === convId) return;
    this.#activeConvId = convId;
    this.#loadedConvId = null;
    this.#generation++;
    this.items = [];
  }

  async load(convId: string, refresh = false): Promise<void> {
    this.activate(convId);
    if (!refresh && this.#loadedConvId === convId) return;
    const generation = ++this.#generation;
    const result = await approvalsApi.list(convId);
    if (generation !== this.#generation || this.#activeConvId !== convId) return;
    this.#loadedConvId = convId;
    this.items = result.approvals;
  }

  async refresh(): Promise<void> {
    if (this.#activeConvId) await this.load(this.#activeConvId, true);
  }

  async decide(item: ApprovalItem, approve: boolean): Promise<void> {
    if (this.deciding) return;
    this.deciding = true;
    try {
      await approvalsApi.decide(item, approve);
      await this.refresh();
    } finally {
      this.deciding = false;
    }
  }

  clear(): void {
    this.#activeConvId = null;
    this.#loadedConvId = null;
    this.#generation++;
    this.items = [];
  }
}

export const approvals = new ApprovalsState();
