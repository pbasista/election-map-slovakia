/* Root page: sends the visitor to /<lang>/. A file rather than an inline
 * script so the Content-Security-Policy can forbid inline scripts. It runs
 * from the <head>, before anything renders, so it reads the config <meta>
 * written above it. */
(() => {
  const c = JSON.parse(document.querySelector('meta[name="km-config"]').content);
  let lang = null;
  try {
    lang = localStorage.getItem(c.storage);
  } catch {
    // Storage disabled: fall through to the browser languages.
  }
  if (!c.codes.includes(lang)) {
    lang = c.fallback[0];
    for (const tag of navigator.languages ?? [navigator.language]) {
      const base = tag.toLowerCase().split('-')[0];
      const code = c.aliases[base] ?? base;
      if (c.codes.includes(code)) {
        lang = code;
        break;
      }
    }
  }
  location.replace(`/${lang}/${location.hash}`);
})();
