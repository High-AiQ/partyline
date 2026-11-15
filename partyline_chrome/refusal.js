// A refusal carries a fixed code. Chrome's own error text can name URLs, so it is never forwarded to
// the helper; `detail` stays in this service worker for its own console.
export const CODES = Object.freeze(['tab_outside_grant', 'tab_owned_by_other_grant', 'previous_detach_incomplete',
  'domain_refused', 'child_outside_grant', 'child_detached', 'revoked', 'restricted_navigation',
  'debugger_attach_failed', 'debugger_command_failed', 'debugger_detached', 'other_extension_frame',
  'restricted_page', 'debugger_already_attached', 'tab_gone', 'unknown']);

export class Refusal extends Error {
  constructor(code, detail = '') {
    super(code);
    this.code = CODES.includes(code) ? code : 'unknown';
    this.detail = String(detail || '').slice(0, 300); // local console only; never serialised
  }
}

export const refuse = (code, detail) => new Refusal(code, detail);

// Which fixed code a failure maps to; a failure that is not a refusal at all is unknown.
export const codeOf = error => (error instanceof Refusal ? error.code : 'unknown');

// Fixed patterns over Chrome's debugger error text, first match wins. The text is matched, never forwarded.
const PATTERNS = [
  ['debugger_detached', /not attached|detached while|target closed|session closed/i],
  ['other_extension_frame', /different extension|cannot access a chrome-extension:/i],
  ['debugger_already_attached', /another debugger is already attached|already attached/i],
  ['restricted_page', /cannot access a chrome:|cannot access contents of|cannot attach to this target|extensions gallery|chrome-untrusted|devtools:\/\//i],
  ['tab_gone', /no tab with given id|tab (was )?closed|no such tab/i],
];

// Classify a Chrome debugger API failure; `fallback` (attach or command phase) names an unrecognised one.
export function chromeFailure(error, fallback) {
  if (error instanceof Refusal) return error;
  const text = String(error?.message || error);
  const found = PATTERNS.find(([, pattern]) => pattern.test(text));
  return refuse(found ? found[0] : fallback, text);
}
