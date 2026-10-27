/* Root page: sends the visitor to /<lang>/. A file rather than an inline
 * script so the Content-Security-Policy can forbid inline scripts. It runs
 * from the <head>, before anything renders, so it reads the config <meta>
 * written above it. */
(() => {
  const c = JSON.parse(document.querySelector('meta[name="km-config"]').content);
  let stored = null;
  try {
    stored = localStorage.getItem(c.storage);
  } catch {
    // Storage disabled: fall through to the browser languages.
  }
  // The first of the browser's languages the site has.
  const browser = () =>
    (navigator.languages ?? [navigator.language])
      .map((tag) => {
        const base = tag.toLowerCase().split('-')[0];
        return c.aliases[base] ?? base;
      })
      .find((code) => c.codes.includes(code));
  const lang = c.codes.includes(stored) ? stored : (browser() ?? c.fallback[0]);
  location.replace(`/${lang}/${location.hash}`);
})();
