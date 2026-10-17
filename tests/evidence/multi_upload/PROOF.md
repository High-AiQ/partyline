# Multi upload UI proof

Captured 2026-10-17 from the new `PartylineClient.upload_files` path using the
throwaway server and database provided by `scripts.uishot.ui_session`.

- `01-six-image-gallery.png`: all six numbered cards appear in input order.
- `02-opened-image-viewer.png`: first card opens in the full size viewer; the
  viewer reports 3000×2000, shows previous/next controls, and reads 1 / 6.
- `03-viewer-download-action.png`: the viewer's original download action is
  visible after activation.
- `04-six-text-attachments.png`: all six generic download cards appear in input
  order, including the CRLF fixture.

The browser-downloaded `01-card.png` was byte-compared with the fixture. Both
were 47,513 bytes and had SHA-256
`2bf8e5e9793d7a74c8d285b74b65869fccd581c0be994cc8c22db61df463c7fd`.

The environment's write-fence preflight warning was removed from the browser
DOM for these targeted captures so it would not cover the gallery controls; no
application UI code was changed.

## Viewer cropping follow-up

The old viewer's portrait stage shrank to 463.5px while the image retained a
496px height, cropping its bottom behind `overflow-hidden`. The new frame
reserves space within the modal for the header, details and controls, and
constrains both image dimensions to that frame. Release stays 2.39.0 as directed.

Captured and visually opened on 2026-10-17, using real `upload_files` requests
against an isolated `scripts.uishot.ui_session` throwaway server/database/media
root. All original evidence above is preserved. New screenshots:

- `05-fitted-six-image-gallery.png`: all six uploaded image thumbnails in order.
- `06-desktop-landscape-fitted.png`: complete 4000×1500 card 04, desktop 1280×800.
- `06-desktop-portrait-fitted.png`: complete 900×3000 card 06, desktop 1280×800.
- `06-narrow-landscape-fitted.png`: complete card 04, narrow 390×844.
- `06-narrow-portrait-fitted.png`: complete card 06, narrow 390×844.
- `07-fitted-six-text-attachments.png`: six generic attachment cards still work.

The card borders are visible on all four sides in each viewer capture. Previous,
next, position, close and download controls remain visible. Finite animations
were finished before capture; the unrelated environment preflight warning
(`#fenceUnavailable`) was removed from this test page only.

Browser regression `tests/ui/test_multi_upload_viewer.py` asserts that the image
box preserves the decoded image's natural aspect ratio, fits within the stage
and viewport, and leaves every control inside the modal and viewport without
scrolling. It actually clicks next, previous, close and download at both sizes.
The portrait containment assertion failed against the accepted old bundle
(image bottom 637px versus stage bottom 603.5px). The existing header/close
browser regression also passes; its stale data-URL fixture was replaced by a
routed SVG so authenticated resource query parameters remain valid.

| Viewport | Card | Rendered image dimensions | Original download bytes | SHA-256 |
| --- | --- | --- | --- | --- |
| 1280×800 | 04 | 936×351 | 277705 | `b732714b04ca64ceae8a0aa7514d8f54aaaf0910f6cb707e342d8cf1343e9b17` |
| 1280×800 | 06 | 133.1875×443.953125 | 130460 | `4fcb092efd41181402cef7100623bf5ddb461de3333ff5fd0c14e1d461f7c512` |
| 390×844 | 04 | 330.390625×123.890625 | 277705 | `b732714b04ca64ceae8a0aa7514d8f54aaaf0910f6cb707e342d8cf1343e9b17` |
| 390×844 | 06 | 144.015625×480.046875 | 130460 | `4fcb092efd41181402cef7100623bf5ddb461de3333ff5fd0c14e1d461f7c512` |

Downloads are retained here as `downloaded-{desktop,narrow}-{04,06}-card.jpg`.
Every download was also compared byte-for-byte against its committed fixture,
matching `tests/fixtures/multi_upload/MANIFEST.sha256`. The originals remain under `tests/fixtures/multi_upload/` and the evidence
under `tests/evidence/multi_upload/` in this checkout. Absolute checkout paths
are reported in the chat handoff, keeping machine identifiers out of the repo.
After merge, the same relative fixture/evidence paths must be present in the
main checkout for native MCP uploads and review.

Reproduce the browser evidence from the repository root:

```bash
PARTYLINE_VIEWER_EVIDENCE="$PWD/tests/evidence/multi_upload" ./scripts/capped-test \
  uv run --locked python -u -m unittest \
  tests/ui/test_multi_upload_viewer.py tests/ui/test_image_viewer.py -v
```

Result: both browser tests pass with a verified 2 GiB process-tree cgroup cap.

Final gate results for this follow-up (bundle build `4de0bee5381e6844`):

- `uv run --locked ruff check .`: passed.
- `./check-code-lines`: passed.
- `./scripts/capped-test`: 2,889 tests passed, 28 skipped, 225.505s;
  verified cgroup `MemoryMax=2G` for the whole process tree.
- `uv run --locked coverage report`: passed the configured 90% gate;
  90.7765% combined statement/branch coverage (displayed as 91%).
  Coverage JSON reports 92.5201% statement coverage and 85.4327% branch coverage
  separately; the configured gate measures their combined result.
- `cd frontend && npm run verify`: formatting and lint passed;
  svelte-check found 0 errors and 0 warnings; 80 test files / 485 tests passed.
- `cd frontend && npm run build`: passed; generated bundle committed with source.
- Final browser evidence rerun against the finished bundle: both tests passed
  in 5.705s under the verified 2 GiB process-tree cap. All six final captures
  were opened and inspected.

The first full-suite attempt overlapped the frontend rebuild, causing two
build-identity assertions to observe different manifests; its hygiene check
also rejected an absolute machine path in this proof. The path was made
relative, the bundle was held fixed, and the full sequential rerun above passed.
