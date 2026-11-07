import type { ScreenRegion } from "../lib/screen-contracts";

export interface RememberedShare {
  line: string;
  device: string;
  region: ScreenRegion;
}

class WalkthroughState {
  choose = $state(0);
  selecting = $state(false);
  shareId = $state<string | null>(null);
  line = $state<string | null>(null);
  last = $state<RememberedShare | null>(null);
  active = $state(false);
}

export const walkthrough = new WalkthroughState();
