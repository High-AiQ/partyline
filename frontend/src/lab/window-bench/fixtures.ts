export const fixtureNames = [
  "shadow-open",
  "shadow-nested",
  "shadow-slotted",
  "shadow-closed",
  "overlay",
  "iframe-same-origin",
  "iframe-cross-origin",
  "select-native",
  "listbox-custom",
  "combobox-filter",
  "input-text",
  "textarea",
  "contenteditable",
  "password",
  "file-input",
  "file-chooser",
  "scroll-container",
  "delayed-animated",
  "modal",
  "toast",
  "navigation",
  "canvas",
  "frame",
] as const;

export type FixtureName = (typeof fixtureNames)[number];

export function fixtureMarkup(name: FixtureName): string {
  const body: Record<FixtureName, string> = {
    "shadow-open": "<open-target></open-target>",
    "shadow-nested": "<nested-target></nested-target>",
    "shadow-slotted": '<slot-target><button id="slotted-target">Slotted target</button></slot-target>',
    "shadow-closed": "<closed-target></closed-target>",
    overlay:
      '<button id="target">Covered button</button><div class="cover" aria-label="Covering overlay">Covered</div>',
    "iframe-same-origin": '<iframe title="Same-origin frame" src="/lab/window-bench/frame.html"></iframe>',
    "iframe-cross-origin": '<iframe title="Cross-origin frame" id="cross-frame"></iframe>',
    "select-native":
      '<label>Native select <select id="target"><option>Choose</option><option>Beta</option></select></label>',
    "listbox-custom":
      '<button id="listbox" role="listbox" aria-label="Custom listbox" aria-expanded="true"><span role="option">Alpha</span><span role="option">Beta</span></button>',
    "combobox-filter":
      '<label>Filter options <input id="combo" role="combobox" aria-expanded="true" aria-controls="options" autocomplete="off"></label><ul id="options" role="listbox"><li role="option">Alpine</li><li role="option">Beta</li></ul>',
    "input-text": '<label>Text input <input id="target" value=""></label>',
    textarea: '<label>Notes <textarea id="target"></textarea></label>',
    contenteditable: '<div id="target" contenteditable="true" aria-label="Editable note">Edit me</div>',
    password: '<label>Password <input id="target" type="password"></label>',
    "file-input": '<label>Choose file <input id="target" type="file"></label>',
    "file-chooser": '<button id="chooser">Open file chooser</button><input id="file" type="file" hidden>',
    "scroll-container":
      '<div class="scroll" id="scroll-box"><button id="target">Off-screen target</button></div>',
    "delayed-animated": '<button id="target">Animated target</button>',
    modal:
      '<dialog aria-label="Example modal"><p>Modal content</p><button id="target">Modal target</button></dialog>',
    toast: '<div role="status" aria-live="polite" id="toast">Toast notification</div>',
    navigation: '<a id="target" href="/lab/window-bench/navigation-result.html">Navigate on click</a>',
    canvas:
      '<canvas id="canvas" width="420" height="140"></canvas><p>Canvas: click the blue visual target.</p>',
    frame: '<button id="frame-target">Frame target</button>',
  };
  const specialState =
    name === "shadow-closed"
      ? "state closedRoot=true"
      : name === "overlay"
        ? "state overlay=true"
        : "state ready";
  return `<h1>${name}</h1><p>Use real input through the granted window. Script-generated events are not trusted.</p><section>${body[name]}</section><p id="fixture-state" aria-label="Fixture state" aria-live="polite">${specialState}</p><section><h2>Trusted event log</h2><ol id="event-log" aria-label="Trusted event log" aria-live="polite"></ol></section>`;
}
