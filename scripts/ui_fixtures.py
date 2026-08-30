"""Stable content fixtures shared by the visual capture harness."""

# One process message exercising the renderer's structural and lazy paths.
AGENT_BODY = r"""## Migration status

Ported the pure libraries to **TypeScript**. Notes for @greg and @sol:

- schemas own the boundary
- `latestJacks()` keeps the *live wins* rule
- see [the contract](https://example.com/contracts)

| module | lines |
|---|---|
| room | 226 |
| wire | 178 |

> A flaky test is worse than an uncovered line.

```js
const jacks = latestJacks(room.attachments);
for (const jack of jacks) {
  console.log(jack.name);
}
```

The reconnect delay follows

\[d_n = \min(2^n, 30)\]
"""
