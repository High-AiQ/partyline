/**
 * Every settings section and every setting in it, as data: the nav, the
 * search box and the deep links all read this one list. A setting appears
 * here only if it exists and does something on this server.
 */
import type { SectionId } from "./settings-route";

export interface SectionInfo {
  id: SectionId;
  label: string;
  blurb: string;
}

export interface SettingInfo {
  /** Also the DOM id of the row, so search results can focus it. */
  id: string;
  section: SectionId;
  label: string;
  description: string;
  keywords?: string;
}

const GENERAL: SectionInfo = {
  id: "general",
  label: "General",
  blurb: "This instance and what every process is told",
};

export const SECTIONS: readonly SectionInfo[] = [
  GENERAL,
  { id: "appearance", label: "Appearance", blurb: "How Partyline looks in this browser" },
  { id: "voice", label: "Voice", blurb: "Microphone and speech recognizers for the composer" },
  { id: "processes", label: "Processes", blurb: "Attach presets, adapters and task history" },
  { id: "resources", label: "Resources", blurb: "How many processes run and how much memory they get" },
  { id: "storage", label: "Storage", blurb: "What Partyline keeps on disk" },
  { id: "computers", label: "Computers", blurb: "Computers paired for screen sharing" },
  { id: "advanced", label: "Advanced", blurb: "Feature flags this server runs with" },
  { id: "about", label: "About", blurb: "Version, build and checkout" },
];

export const SETTINGS: readonly SettingInfo[] = [
  {
    id: "setting-instance-name",
    section: "general",
    label: "Instance name",
    description: "The label shown above every line; set in the server config or environment",
    keywords: "banner label server",
  },
  {
    id: "setting-global-prose",
    section: "general",
    label: "Global prose",
    description: "Text added to every process briefing when it next joins or resumes",
    keywords: "instructions briefing prompt",
  },
  {
    id: "setting-review-environments",
    section: "general",
    label: "Review environments",
    description: "Repository setup and test commands for review checkouts",
    keywords: "lockfile dependencies test setup",
  },
  {
    id: "setting-theme",
    section: "appearance",
    label: "Theme",
    description: "Light, dark, or follow the system setting",
    keywords: "dark mode light mode colour color",
  },
  {
    id: "setting-voice-pause",
    section: "voice",
    label: "Hands-free speech pause",
    description: "Silence before automatically transcribing and sending speech",
    keywords: "vad hands free hands-free voice pause silence automatic send",
  },
  {
    id: "setting-voice-hidden",
    section: "voice",
    label: "Release hidden microphone",
    description: "How long a hidden tab keeps its hands-free microphone",
    keywords: "hands free hands-free background privacy timeout microphone",
  },
  {
    id: "setting-voice-microphone",
    section: "voice",
    label: "Microphone",
    description: "Choose which microphone to record from, and test its level",
    keywords: "mic input device audio headset level meter test muted allow permission",
  },
  {
    id: "setting-voice-mic",
    section: "voice",
    label: "Use for my mic",
    description: "Which recognizer the composer microphone uses in this browser",
    keywords: "asr transcribe whisper microphone speech dictation choose recognizer",
  },
  {
    id: "setting-asr-presets",
    section: "voice",
    label: "Speech recognizers",
    description:
      "Presets for the microphone: local faster-whisper, an OpenAI-compatible service, or a command",
    keywords: "asr transcribe whisper openai mic microphone speech to text dictation default order test",
  },
  {
    id: "setting-asr-add",
    section: "voice",
    label: "Add a recognizer",
    description: "Create a preset; it applies at once, without a restart",
    keywords: "new preset asr",
  },
  {
    id: "setting-asr-keys",
    section: "voice",
    label: "API keys",
    description:
      "Keys stay in the server environment; a preset names the variable and shows only set or unset",
    keywords: "secret token OPENAI_API_KEY env .env",
  },
  {
    id: "setting-process-presets",
    section: "processes",
    label: "Process presets",
    description: "Saved attach forms: handle, adapter, command and traits",
    keywords: "attach preset jack",
  },
  {
    id: "setting-adapters",
    section: "processes",
    label: "Adapters",
    description: "Import process adapters from a git repository",
    keywords: "import cli harness",
  },
  {
    id: "setting-task-history",
    section: "processes",
    label: "Auto-clean task history",
    description: "Archive approved or done tasks after merge and remove their worktrees",
    keywords: "orchestrator review cleanup",
  },
  {
    id: "setting-max-compactions",
    section: "processes",
    label: "Maximum compactions per process",
    description:
      "After this many compactions a process is replaced by a fresh instance briefed from its hand-off note; 0 turns it off",
    keywords: "compact rotate fresh restart context handoff",
  },
  ...(
    [
      ["max-live-processes", "Maximum live processes", "How many processes may run at once"],
      ["memory-reserve", "Memory reserve", "RAM kept back for the host and everything else"],
      ["process-memory", "Default process memory budget", "Per-process soft budget that warnings track"],
      ["memory-reservation", "Memory reservation", "Admission estimate per process; it limits nothing"],
      ["memory-warning", "Early memory warning", "Budget percentage for pressure-event warnings"],
      ["captain-ceiling", "Captain approval ceiling", "Memory requests above this need a person"],
    ] as const
  ).map(([id, label, description]): SettingInfo => ({
    id: `setting-${id}`,
    section: "resources",
    label,
    description,
    keywords: "resource budget memory ram admission",
  })),
  {
    id: "setting-storage",
    section: "storage",
    label: "Storage usage",
    description: "Disk used by lines, media and worktrees; clear what Partyline can recreate",
    keywords: "disk space clear cache media",
  },
  {
    id: "setting-screen-devices",
    section: "computers",
    label: "Screen sharing computers",
    description: "Pairing codes and paired computers for the native screen helper",
    keywords: "screen share desktop helper pair device",
  },
  {
    id: "setting-feature-flags",
    section: "advanced",
    label: "Feature flags",
    description: "Named switches set in the server config or environment",
    keywords: "flags experimental heartbeat fence",
  },
  {
    id: "setting-version",
    section: "about",
    label: "Version and build",
    description: "Release version, frontend build, git head and checkout path",
    keywords: "release commit sha about",
  },
];

export function sectionInfo(id: SectionId): SectionInfo {
  return SECTIONS.find((section) => section.id === id) ?? GENERAL;
}

/** Every word of the query must appear in a setting's label, description, keywords or section. */
export function searchSettings(query: string, settings: readonly SettingInfo[] = SETTINGS): SettingInfo[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  return settings.filter((setting) => {
    const haystack = [
      setting.label,
      setting.description,
      setting.keywords ?? "",
      sectionInfo(setting.section).label,
    ]
      .join(" ")
      .toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** How many results each section holds, for the nav while a search is active. */
export function countBySection(results: readonly SettingInfo[]): Map<SectionId, number> {
  const counts = new Map<SectionId, number>();
  for (const result of results) counts.set(result.section, (counts.get(result.section) ?? 0) + 1);
  return counts;
}
