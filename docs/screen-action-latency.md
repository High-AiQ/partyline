# UIA action latency audit

Read the top-level `timing` on `screen_element_action`, `screen_elements` (including inspect),
and `screen_window_snapshot`. Durations are local monotonic milliseconds, summed across repeated
phases. `helper_` means measured on the helper; unprefixed phases are on the server.
`server_total_ms`, `helper_roundtrip_ms`, `helper_action_total_ms`, `helper_read_ms`, and
`helper_total_ms` overlap their component phases: do not add them together. Tool-call telemetry
stores the same allowlisted timing object in `tool_calls.metrics`; its overall `latency_ms`
also includes the MCP/HTTP path. For a live-run database export, select
`json_extract(metrics,'$.timing')` from `tool_calls` alongside its timestamp, tool, and action. No names, values, queries, or observation text enter timings.

`request_queue_ms` starts at ASGI middleware receipt and ends at the screen operation's entry
(direct internal calls without an HTTP request report zero). `window_lock_ms`
measures server contention; `send_ms` measures its websocket send; `helper_roundtrip_ms` is the
subsequent wait for the response. Helper `task_queue_ms` and `worker_queue_ms` distinguish event-loop
scheduling from thread scheduling. `initialize_ms` includes child Python/COM startup and the initial
cache fetch for reads. `target_ms` includes path lookup and bounded fallback re-find. `foreground_ms`
includes checks and conditional restoration. `uia_ms` measures dispatch; `post_read_ms` measures its
state observation. `barrier_ms` and `helper_barrier_ms` distinguish server event-counter round trips
from helper quiet waiting; `helper_barrier_stop` is `unchanged`, `quiet`, `deadline`, or `unsupported`.
`walk_ms`, `nodes`, and `com_calls` expose capture cost. COM calls count explicit method calls and
property accessors, including cached/local COM calls; they are not all remote provider round trips.
`diff_ms`, `answer_ms`, and `snapshot_store_ms` measure server work. Helper `reply_ms` measures writer
queueing and the final consent gate through packet preparation, before the first byte; a packet cannot
report its own completed send. Screenshot `capture_ms`/`encode_ms` and server `image_store_ms` separate
pixel capture, compression, and media storage.

The following are ranked static hypotheses, **not measurements on Greg's PC**. Savings overlap;
helper 1.3.0 must be deployed and the Catalog Dashboard sequence repeated to establish the subsecond target.

| Rank | Likely cost | Change or reason retained | Expected saving to verify live |
| --- | --- | --- | --- |
| 1 | Press made two browser-chrome scans of up to 256 nodes, each reading full live UIA properties/patterns; Enter also inspected up to 80 siblings | Observe only the target and window title; URL evidence only when the target is an address control. Test sibling control types before reading submit-button properties. Reuse pre-focus ancestry for submit lookup/targeting, and read only control type there, rather than all patterns | Potentially seconds of the 4.7 s press/invoke gap; hundreds to thousands of COM calls disappear |
| 2 | Fresh query reads prefetched and walked the whole window, even for one matching name | UIA FindAllBuildCache uses name/type conditions and an element-only cache; only matches and ancestors are described. Anchors are filtered again by the server. Runtime IDs are cached. Full cached trees can still answer any query | Most full-walk/serialization cost on selective queries; compare with the observed 1.2 s snapshot baseline. Startup and provider-side search remain |
| 3 | Every action resolved and validated its target twice, walking child indices and fetching live state twice | Resolve once after checking the grant's window, then retain the live node for dispatch and observation; dispatch still checks consent/window identity | One full target-resolution pass and duplicate selected/expand-state pattern reads, plausibly hundreds of ms for deep browser trees |
| 4 | TTL-expired action targets and forced reads first checked the cache's counter, then discarded that cache anyway | For expired action targets, reuse the existing ID mapping only after a live matching event-counter proof; helper dispatch still validates runtime identity/path. Skip the redundant pre-refresh cache barrier. Keep capture validation and final counter check after rendering | A whole recapture after idle on an unchanged window, plus one redundant round trip on refresh |
| 5 | Events during capture could repeatedly restart a large capture | After observed action events, wait on their condition until 20 ms quiet, capped at 200 ms. New events wake the condition; no observed events means no wait | Avoid repeated captures during brief churn; costs up to 20 ms after the last observed event instead of a fixed settle delay |
| 6 | Python/COM child startup and cache preparation on every read | Retained process kill isolation and bounded startup/walk deadlines. They are maximums, never sleeps. Filtered reads avoid the initial full-tree cache fetch | No claimed startup saving; initialize_ms makes this next candidate measurable |
| 7 | Broad snapshot cache properties and cross-thread contention | Snapshot cache properties are used for IDs, state, actions, bounds, redaction, or window scoping. Event callbacks only increment a short condition-protected counter; quiet waits release that lock, and it is independent of the dispatch gate | No speculative property removals; counters show whether cached COM access remains material |
| 8 | 100 ms pushed-change debounce | Retained off the action/read path: the event counter advances synchronously before a push is coalesced. Reads validate the counter directly | Zero critical-path delay from this debounce |
| 9 | Native screenshot capture, PNG encoding, media transforms | Instrumented separately; no speculative quality/format changes | No claimed saving |

Filtered matches still require control-view path reconstruction: each newly encountered ancestor
calls `children`, which uses an all-children `BuildUpdatedCache` in shallow mode. Shared ancestors
are reused within a query, but wide/deep ancestor chains can remain costly; watch `helper_walk_ms`
and `helper_com_calls` for this residual cost before claiming a selective query is cheap.

A filtered capture is not a complete tree or a whole-window diff. The server records its query scope,
preserves known stable IDs and uses validated helper runtime/path IDs for newly found nodes, and recaptures for another scope or a summary.
Earlier full-capture and query IDs remain in a bounded action-only fallback map; the helper merges
its target paths without resetting the full walk's epoch or cursors. These retained IDs never supply
cached answers: actions must still pass the helper's live runtime/path identity and consent checks.
A new full capture or revocation clears the fallback. The retained map has the same 120,000-ID cap
as a full tree, and counts toward server cache eviction. A match that disappears mid-walk is skipped
and the capture is marked changed, preserving event-counter retry/inconsistency reporting.
A capped filtered result is explicitly partial. Text/context, value, and root queries keep the full
capture path; they require structure beyond a name/type filter. A fresh complete cached tree is reused
for filtered queries after its normal event-counter barrier. Older helpers ignore the new query field
and continue providing complete trees. Stale identity, password redaction, consent generation checks,
and event-counter validation before cache reuse and after capture remain mandatory.

Windows-only tests read for these changes: `tests/test_windows_uia.py`, `tests/windows_uia_patterns.py`,
`tests/windows_uia_window.py`. The Windows integration test now exercises native filtered capture and
checks that it neither includes unrelated controls nor changes the foreground window. The other two
fixtures remain unchanged. Native COM execution requires the `windows-foundations` CI job; Linux tests
use fake providers, clocks, events, and Win32 message delivery.
