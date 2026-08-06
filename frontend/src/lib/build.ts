/**
 * Whether the JavaScript running in this tab differs from the build the server
 * just identified. Blank ids mean an old server or `npm run dev`; neither is a
 * reason to enter a reload loop.
 */
export const buildChanged = (clientBuild: string, serverBuild: string | undefined): boolean =>
  Boolean(clientBuild && serverBuild && clientBuild !== serverBuild);

/**
 * How to describe the code this document is running, for a person.
 *
 * The version badge answers "what server am I connected to"; this answers "is
 * my browser running the current code". They are different questions with
 * different answers — a Python-only release moves the version and leaves the
 * bundle alone — and conflating them is what left a badge reading `v0.21.1`
 * against a `v0.21.3` server with nothing wrong.
 *
 * `npm run dev` compiles a blank id on purpose, and saying so is more useful
 * than showing an empty string.
 */
export const describeBuild = (clientBuild: string): string =>
  clientBuild ? `build ${clientBuild}` : "dev build";
