# Live MCP verification records

These records capture native calls made by service-managed attachments. The
Codex resume comparison uses one attachment and session to distinguish the
deployed adapter from a one-off diagnostic command override:

| Record | Runtime condition | Result |
| --- | --- | --- |
| [`resume-before.md`](resume-before.md) | Codex before normal service detach/resume | Native `whoami` and `guide` succeeded. The native snapshot did not expose the Codex session ID; service metadata identifies the `cli_session` used for both subsequent resumes. |
| [`resume-after.md`](resume-after.md) | Normal service resume with the then-deployed adapter, whose generated `-c` overrides preceded `resume <id>` | No Partyline tools were registered; startup log selection had no Partyline row. |
| [`resume-after-diagnostic-override.md`](resume-after-diagnostic-override.md) | Same attachment and service-reported session after a single attachment-only diagnostic override moved generated `-c` overrides after `resume <id>` | Ten Partyline tools appeared; native `whoami` and `guide` succeeded. This is **diagnostic override evidence**, not proof from the deployed adapter. |
| [`codex-luna-2026-10-17.md`](codex-luna-2026-10-17.md) | Initial fresh Codex attachment and pre-fix source inspection | Native calls succeeded; the title-generation log's `invalid transport` error did not identify a missing field. Historical placement analysis is superseded by the same-session resume comparison above. |
| [`2026-10-17-opencode-v2-glm-flash-service-managed.md`](2026-10-17-opencode-v2-glm-flash-service-managed.md) | Installed `glm-flash` OpenCode V2 preset, attached through the normal service API | Native `whoami` and `guide` succeeded; `captain` returned the expected non-captain denial. |

Service-observed metadata for attachment `3ba5a31d-3f41-4a64-a384-396c9cd53ff1`
reported `cli_session` `01a14a1b-2f41-76f1-b65b-f6dc6c545ca1` on both resumes;
both process argvs began `codex resume 01a14a1b-2f41-76f1-b65b-f6dc6c545ca1 ...`.
The service constructs that argument from the attachment's `cli_session`
recorded before detach, so continuity rests on that manager-observed metadata,
not a matching ID in the native pre-resume snapshot. No raw pre-detach
`cli_session` API response was retained.

The adapter fix and its argv regressions are covered in the source and tests;
these live records retain the runtime evidence that motivated the change.
