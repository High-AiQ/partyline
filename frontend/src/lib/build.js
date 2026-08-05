/**
 * Whether the JavaScript running in this tab differs from the build the server
 * just identified. Blank ids mean an old server or `npm run dev`; neither is a
 * reason to enter a reload loop.
 */
export const buildChanged = (clientBuild, serverBuild) =>
  Boolean(clientBuild && serverBuild && clientBuild !== serverBuild);
