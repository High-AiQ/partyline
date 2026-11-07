import { formatElapsed } from "./voice";

export type WalkthroughStage = "idle" | "waiting" | "starting" | "recording" | "finishing";

/** The one-line status shown while a walkthrough is under way. */
export function stageText(stage: WalkthroughStage, elapsedMs: number): string {
  if (stage === "waiting") return "Choose a screen and allow sharing…";
  if (stage === "starting") return "Opening microphone…";
  if (stage === "recording") return `● Recording walkthrough ${formatElapsed(elapsedMs)}`;
  return "Preparing walkthrough…";
}
