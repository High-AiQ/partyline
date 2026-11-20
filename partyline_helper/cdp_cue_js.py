"""What the cue asks the page: its viewport numbers, and the focused element for the box."""
METRICS = """(() => {
 const v = window.visualViewport;
 return JSON.stringify([document.visibilityState === 'visible', window.devicePixelRatio,
   v ? v.scale : 1, window.innerWidth, window.innerHeight]);
})()"""
FOCUSED = """(() => {
 let a = document.activeElement;
 for (let i = 0; a && i < 20; i++) {
  if (a.shadowRoot && a.shadowRoot.activeElement) { a = a.shadowRoot.activeElement; continue; }
  if (a.tagName === 'IFRAME' || a.tagName === 'FRAME') {
   let d = null; try { d = a.contentDocument; } catch (e) { d = null; }
   if (!d || !d.activeElement) return null;
   a = d.activeElement; continue;
  }
  break;
 }
 return !a || a === document.body || a === document.documentElement ? null : a;
})()"""
