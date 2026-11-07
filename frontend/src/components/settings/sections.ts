/**
 * Which component draws each section. The ids, labels and search entries live
 * in `lib/settings-registry.ts`; this is only the drawing. A section that grows
 * (Computers, when screen pairing lands) replaces its own component and leaves
 * the shell, routing and search untouched.
 */
import type { Component } from "svelte";
import type { SectionId } from "../../lib/settings-route";
import GeneralSection from "./sections/GeneralSection.svelte";
import AppearanceSection from "./sections/AppearanceSection.svelte";
import VoiceSection from "./sections/VoiceSection.svelte";
import ProcessesSection from "./sections/ProcessesSection.svelte";
import ResourcesSection from "./sections/ResourcesSection.svelte";
import StorageSettings from "./sections/StorageSettings.svelte";
import ComputersSection from "./sections/ComputersSection.svelte";
import AdvancedSection from "./sections/AdvancedSection.svelte";
import AboutSection from "./sections/AboutSection.svelte";

export const SECTION_COMPONENTS: Record<SectionId, Component> = {
  general: GeneralSection,
  appearance: AppearanceSection,
  voice: VoiceSection,
  processes: ProcessesSection,
  resources: ResourcesSection,
  storage: StorageSettings,
  computers: ComputersSection,
  advanced: AdvancedSection,
  about: AboutSection,
};
