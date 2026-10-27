/* Light or dark: the visitor's choice, else the device's.
 *
 * A classic script loaded from <head>, so `data-theme` is on <html> before
 * the first paint; a file because the Content-Security-Policy forbids inline
 * scripts. app.css colours both themes from that attribute, and the map
 * (map.js) redraws its canvas on `themechange`. The app's theme button and
 * menu go through `globalThis.emsTheme`, so the storage key lives only here.
 */
(() => {
  const KEY = 'election-map-slovakia.theme';
  const MODES = ['system', 'light', 'dark'];
  const root = document.documentElement;
  const dark = matchMedia('(prefers-color-scheme: dark)');
  const device = () => (dark.matches ? 'dark' : 'light');
  let mode = 'system';
  try {
    const stored = localStorage.getItem(KEY);
    if (MODES.includes(stored)) mode = stored;
  } catch {
    // Storage disabled: the device's theme it is.
  }

  function apply() {
    const theme = mode === 'system' ? device() : mode;
    if (root.dataset.theme === theme) return;
    root.dataset.theme = theme;
    document.dispatchEvent(new Event('themechange'));
  }

  apply();
  dark.addEventListener('change', apply);

  function set(next) {
    mode = next;
    try {
      if (next === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // Storage disabled: the choice holds for this visit.
    }
    apply();
  }

  globalThis.emsTheme = {
    modes: MODES,
    get mode() {
      return mode;
    },
    set,
    /* The theme button's click: device, the device's opposite, the device's
     * own, device again. Leaving "device" thus always changes the colours;
     * a fixed light-then-dark order would do nothing visible on the first
     * click on a light device. Returns the new mode. */
    cycle() {
      const own = device();
      const opposite = own === 'dark' ? 'light' : 'dark';
      set(mode === 'system' ? opposite : mode === opposite ? own : 'system');
      return mode;
    },
  };
})();
