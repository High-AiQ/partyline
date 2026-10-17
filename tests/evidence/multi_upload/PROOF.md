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
