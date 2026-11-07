/** Device-local preferences, shared by Settings and the composer in this tab. */
import { z } from "zod";
const KEY = "partyline.voice.hands-free";
const Preferences = z.object({
  enabled: z.boolean().default(false),
  pauseMs: z.number().min(600).max(3000).default(1400),
  hiddenMs: z.number().min(10_000).max(600_000).default(60_000),
});
type Preferences = z.infer<typeof Preferences>;
function read(): Preferences {
  try {
    return Preferences.parse(JSON.parse(localStorage.getItem(KEY) ?? "{}"));
  } catch {
    return Preferences.parse({});
  }
}
export class HandsFreePreferences {
  value = $state(read());
  update(next: Partial<Preferences>): void {
    this.value = Preferences.parse({ ...this.value, ...next });
    try {
      localStorage.setItem(KEY, JSON.stringify(this.value));
    } catch {
      /* A private browser can still listen without remembering the choice. */
    }
  }
}
export const handsFree = new HandsFreePreferences();
