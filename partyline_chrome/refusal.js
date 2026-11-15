// A refusal carries a fixed code. Chrome's own error text can name URLs, so it is never forwarded.
export const CODES = Object.freeze(['tab_outside_grant', 'tab_owned_by_other_grant', 'previous_detach_incomplete',
  'domain_refused', 'child_outside_grant', 'child_detached', 'revoked', 'restricted_navigation',
  'debugger_attach_failed', 'debugger_command_failed', 'debugger_detached']);

export class Refusal extends Error {
  constructor(code) {
    super(code);
    this.code = CODES.includes(code) ? code : 'debugger_command_failed';
  }
}

export const refuse = code => new Refusal(code);

// Which fixed code a failure maps to; an unknown failure is a failed debugger command.
export const codeOf = error => (error instanceof Refusal ? error.code : 'debugger_command_failed');

// Classify a Chrome debugger API failure without keeping its text.
export function chromeFailure(error, fallback) {
  if (error instanceof Refusal) return error;
  return refuse(/not attached|detached while|no tab with given id|target closed|session closed/i.test(String(error?.message || error))
    ? 'debugger_detached' : fallback);
}
