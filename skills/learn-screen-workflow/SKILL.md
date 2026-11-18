---
name: learn-screen-workflow
description: Learn a reusable screen workflow from an authorized demonstration or history interval, validate it on held-out values, and prepare an unapproved draft for person review.
---

# Learn a screen workflow

Use this procedure at high reasoning effort to propose a reusable workflow from a demonstration. The tools supply evidence; they do not learn or approve on your behalf.

1. Read the demonstration and align each authorized call with its semantic observations and narration. For history, use only arguments retained in structured `tool_calls` and transcript records. Mark a step unresolved whenever its action, target, or result is absent. Ask for a focused demonstration rather than inferring missing evidence.
2. Compare repeated calls. Extract values that vary as typed parameters, including text, choices, records, and lists. Keep stable control roles, labels, and scopes in the workflow. Resolve a row from its header or supplied row label, then resolve a field by its column label; do not depend on incidental order when labels are available.
3. Choose preconditions and postconditions from observed before and after state. Ask the person what success means when the demonstration does not establish it. Mark `confirm: true` and describe the effect for irreversible steps.
4. Validate the complete bundle, then preview against held-out values with different text and collection sizes. Preview is read-only. Fix missing, ambiguous, and multiply matched targets before proposing.
5. Write the root and every referenced component under the line checkout's normal write fence. Call `screen_workflow_draft` with the demonstration ID, root workflow name, and an alignment map from each root step ID to a narration line index. Keep narration's timestamp association separate from calls unless the evidence identifies an exact call. The tool validates the complete bundle and saves an unapproved review record. Report unresolved evidence and preview findings. Never approve, invoke an approval route, or describe a draft as runnable. A person reviews and approves the exact content hash.
