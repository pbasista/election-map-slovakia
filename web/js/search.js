/* One search box for municipalities, streets, parts of municipalities, house
 * numbers and candidates.
 *
 * addr/index.json (see addresses.py) loads on first focus. Names match by
 * prefix of their search key, either from the start or from any word. A
 * query is "<name> [number][, <obec or okres>]": `Račianska 154,
 * Bratislava-Rača`. Picking a street or part without a number scopes the box
 * to it and lists its house numbers from addr/<obec>.json. Candidate names
 * come from the name shards (see build.py).
 *
 * ARIA combobox (1.2 pattern): the input owns a listbox popup and points to
 * the active option with aria-activedescendant; focus stays in the input.
 */

import { html, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { contestLabel, dataIndex, findPersons, searchKey } from './data.js';
import { addressFile, fetchJSON } from './files.js';
import { t } from './i18n.js';
import { CloseIcon, SearchIcon } from './icons.js';

const LIMITS = { obec: 5, street: 8, part: 4, person: 6, number: 40 };
// With this few streets or parts matching a query with a number, their files
// load at once and the matching houses are listed directly.
const DIRECT_FILES = 4;
const NUMBER = /^(.*\S)\s+(\d+\s*\p{L}?(?:\s*\/\s*\d*\s*\p{L}?)?)$/u;

let addressIndex = null;
function loadIndex() {
  addressIndex ??= fetchJSON('/addr/index.json').then((ix) => {
    const obce = ix.obce.map(([code, name, okres, key]) => ({ code, name, okres, key }));
    const okresKeys = Object.fromEntries(
      Object.entries(ix.okresy).map(([code, name]) => [code, searchKey(name)]),
    );
    return {
      okresy: ix.okresy,
      okresKeys,
      obce,
      byCode: new Map(obce.map((o) => [o.code, o])),
      streets: ix.streets,
      parts: ix.parts,
    };
  });
  addressIndex.catch(() => {
    addressIndex = null;
  });
  return addressIndex;
}

/* 0: the key starts with the query; 1: a later word does; -1: no match. */
function rank(key, q) {
  if (key.startsWith(q)) return 0;
  if (key.includes(` ${q}`)) return 1;
  return -1;
}

function parse(raw) {
  const comma = raw.indexOf(',');
  const main = (comma < 0 ? raw : raw.slice(0, comma)).trim();
  const context = comma < 0 ? '' : searchKey(raw.slice(comma + 1));
  const m = main.match(NUMBER);
  if (m) return { name: searchKey(m[1]), number: normalNumber(m[2]), context };
  return { name: searchKey(main), number: '', context };
}

const normalNumber = (s) => s.replace(/\s+/g, '').toLowerCase();

/* How well house number *shown* ("2811/154", "125") matches what was typed:
 * lower is better, -1 is no match. The orientačné číslo (after the slash)
 * is the number on the street side, so it ranks first. */
function numberRank(shown, typed) {
  const s = shown.toLowerCase();
  if (!typed) return 0;
  const parts = s.split('/');
  const last = parts[parts.length - 1];
  if (s === typed || last === typed) return 0;
  if (parts.includes(typed)) return 1;
  if (last.startsWith(typed)) return 2;
  if (s.startsWith(typed) || parts.some((p) => p.startsWith(typed))) return 3;
  return -1;
}

function houseOptions(code, obecName, groups, typed, limit) {
  const found = [];
  for (const group of groups) {
    group.numbers.forEach((n, i) => {
      const r = numberRank(n, typed);
      if (r >= 0) found.push({ r, group, i });
    });
  }
  found.sort((a, b) => a.r - b.r);
  return found.slice(0, limit).map(({ group, i }) => ({
    type: 'number',
    code,
    group,
    i,
    label: `${group.name} ${group.numbers[i]}`,
    detail: obecName,
  }));
}

const collator = new Intl.Collator('sk');
const byRank = (a, b) =>
  a.r - b.r || a.c - b.c || collator.compare(a.name, b.name) || collator.compare(a.where, b.where);

async function search(raw, scope) {
  const ix = await loadIndex();
  if (scope) {
    const file = await addressFile(scope.code);
    const group = file.groups.find((g) => g.kind === scope.kind && g.name === scope.name);
    const typed = normalNumber(raw.slice(scope.prefix.length));
    return houseOptions(scope.code, ix.byCode.get(scope.code).name, [group], typed, LIMITS.number);
  }
  const q = parse(raw);
  if (!q.name) return [];
  /* How well the obec of *code* matches the part after the comma: 0 by its
   * name (or when there is no such part), 1 by a later word of its name, 2
   * by its okres; -1 not at all. */
  const context = (code) => {
    if (!q.context) return 0;
    const o = ix.byCode.get(code);
    const r = rank(o.key, q.context);
    if (r >= 0) return r;
    return rank(ix.okresKeys[o.okres], q.context) >= 0 ? 2 : -1;
  };
  const obce = [];
  for (const o of ix.obce) {
    const r = rank(o.key, q.name);
    const c = r >= 0 ? context(o.code) : -1;
    if (c >= 0) obce.push({ r, c, name: o.name, where: '', o });
  }
  obce.sort(byRank);
  const named = (list, type) => {
    const out = [];
    for (const [name, key, codes] of list) {
      const r = rank(key, q.name);
      if (r < 0) continue;
      for (const code of codes) {
        const c = context(code);
        if (c >= 0) out.push({ r, c, name, where: ix.byCode.get(code).name, type, code });
      }
    }
    return out.sort(byRank);
  };
  const streets = named(ix.streets, 'street');
  const parts = named(ix.parts, 'part');

  if (q.number) {
    const targets = [...streets, ...parts];
    if (targets.length + obce.length <= DIRECT_FILES) {
      const lists = await Promise.all([
        ...targets.map(async (s) => {
          const file = await addressFile(s.code);
          const kind = s.type === 'street' ? 'streets' : 'parts';
          const groups = file.groups.filter((g) => g.kind === kind && g.name === s.name);
          return houseOptions(s.code, ix.byCode.get(s.code).name, groups, q.number, LIMITS.number);
        }),
        // Villages number their houses within the parts of the obec.
        ...obce.map(async ({ o }) => {
          const file = await addressFile(o.code);
          const groups = file.groups.filter((g) => g.kind === 'parts');
          return houseOptions(o.code, o.name, groups, q.number, LIMITS.number);
        }),
      ]);
      const houses = lists.flat();
      if (houses.length) return houses.slice(0, LIMITS.number);
    }
  }

  const options = [
    ...obce.slice(0, LIMITS.obec).map(({ o }) => ({
      type: 'obec',
      code: o.code,
      label: o.name,
      detail: t('search.okres', { name: ix.okresy[o.okres] }),
    })),
    ...[...streets.slice(0, LIMITS.street), ...parts.slice(0, LIMITS.part)].map((s) => ({
      type: s.type,
      code: s.code,
      name: s.name,
      number: q.number,
      label: q.number ? `${s.name} ${q.number}` : s.name,
      detail: ix.byCode.get(s.code).name,
    })),
  ];
  if (!q.number && !q.context && q.name.length >= 2) {
    const [persons, index] = await Promise.all([findPersons(q.name, LIMITS.person), dataIndex()]);
    for (const p of persons) {
      const more = p.candidacies.length > 1 ? ` +${p.candidacies.length - 1}` : '';
      options.push({
        type: 'person',
        candidacy: p.candidacies[0],
        label: t('search.person', { name: p.name, age: p.age }),
        detail: `${contestLabel(p.candidacies[0].split('#')[0], index)}${more}`,
      });
    }
  }
  return options;
}

/* The search card: the site's title (*children*) with a search button, which
 * turns the card into the search box in place; `/`, Ctrl+K and ⌘K open it
 * from anywhere. The box stays while it holds text; empty and left, or on
 * Esc or its close button, it turns back into the title.
 *
 * `onPlace(place, view)` selects a place (see map.js `select` for *view*);
 * `onCandidate(id)` opens a candidate. */
export function Search({ onPlace, onCandidate, children }) {
  const [shown, setShown] = useState(false);
  const [query, setQuery] = useState('');
  const [options, setOptions] = useState([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState('');
  const scope = useRef(null);
  const sequence = useRef(0);
  const input = useRef(null);
  const box = useRef(null);
  const opener = useRef(null);
  const refocus = useRef(false);

  function show() {
    // Shown and focused right here rather than after the re-render: phones
    // open the keyboard only for focus given while handling the tap.
    box.current.hidden = false;
    input.current.focus();
    setShown(true);
  }

  /* Back to the title; with *focusTitle*, focus goes to its button rather
   * than being lost with the box. */
  function hide(focusTitle) {
    sequence.current++;
    scope.current = null;
    setQuery('');
    setOptions([]);
    setStatus('');
    setOpen(false);
    setShown(false);
    refocus.current = focusTitle;
  }

  useEffect(() => {
    if (shown || !refocus.current) return;
    refocus.current = false;
    opener.current.focus();
  }, [shown]);

  useEffect(() => {
    const onKey = (e) => {
      const slash = e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey;
      const k = e.key.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey;
      if (e.defaultPrevented || !(slash || k)) return;
      // `/` is typed as usual in fields; the About dialog keeps focus inside.
      if (slash && e.target.closest?.('input, textarea, select, [contenteditable]')) return;
      if (e.target.closest?.('dialog')) return;
      e.preventDefault();
      if (input.current !== document.activeElement) show();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  async function run(text) {
    const seq = ++sequence.current;
    if (scope.current && !text.startsWith(scope.current.prefix)) scope.current = null;
    if (!text.trim()) {
      setOptions([]);
      setStatus('');
      return;
    }
    setStatus(t('search.loading'));
    try {
      const found = await search(text, scope.current);
      if (seq !== sequence.current) return;
      setOptions(found);
      setActive(found.length ? 0 : -1);
      setOpen(true);
      setStatus(found.length ? t('search.count', { n: found.length }) : t('search.none'));
    } catch (e) {
      console.error(e);
      if (seq === sequence.current) setStatus(t('error.load'));
    }
  }

  // A place or candidate chosen shows in the pane, so the box gives way to the
  // title again; a street or part stays, listing its house numbers.
  async function choose(option) {
    if (option.type === 'obec') {
      hide(true);
      onPlace({ obec: option.code }, 'obec');
    } else if (option.type === 'number') {
      const { group, i } = option;
      hide(true);
      onPlace(
        {
          obec: option.code,
          lat: group.lat[i],
          lon: group.lon[i],
          label: option.label,
          obvod: group.obvody?.[i] ?? null,
        },
        'place',
      );
    } else if (option.type === 'person') {
      hide(true);
      onCandidate(option.candidacy);
    } else {
      const kind = option.type === 'street' ? 'streets' : 'parts';
      const prefix = `${option.name} `;
      scope.current = { code: option.code, kind, name: option.name, prefix };
      const text = prefix + (option.number ?? '');
      setQuery(text);
      // The map highlights the street or part and fits the view to it.
      onPlace({ obec: option.code, [option.type]: option.name }, 'place');
      input.current?.focus();
      await run(text);
    }
  }

  const expanded = open && options.length > 0;

  function onKeyDown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      if (!options.length) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive((a) => (a + step + options.length) % options.length);
    } else if (e.key === 'Enter') {
      if (open && active >= 0 && options[active]) {
        e.preventDefault();
        choose(options[active]);
      }
    } else if (e.key === 'Escape') {
      // Not the browser's own clearing of the box: Esc closes the list first.
      e.preventDefault();
      if (expanded) setOpen(false);
      else hide(true);
    }
  }

  useEffect(() => {
    if (active >= 0) document.getElementById(`km-opt-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  return html`
    <div class="title" hidden=${shown}>
      <h1 class="brand">${children}</h1>
      <button
        type="button"
        class="search-open"
        ref=${opener}
        aria-label=${t('search.label')}
        title=${t('search.open')}
        aria-expanded=${shown}
        aria-controls="km-search-box"
        aria-keyshortcuts="/ Control+K Meta+K"
        onClick=${show}
      >
        <${SearchIcon} />
      </button>
    </div>
    <div class="search" id="km-search-box" ref=${box} hidden=${!shown}>
      <${SearchIcon} />
      <input
        ref=${input}
        id="km-search"
        type="search"
        role="combobox"
        autocomplete="off"
        spellcheck=${false}
        aria-autocomplete="list"
        aria-expanded=${expanded}
        aria-controls="km-search-list"
        aria-activedescendant=${expanded && active >= 0 ? `km-opt-${active}` : undefined}
        aria-describedby="km-search-status"
        aria-label=${t('search.label')}
        placeholder=${t('search.placeholder')}
        value=${query}
        onFocus=${() => {
          loadIndex().catch((e) => console.error(e));
          if (options.length) setOpen(true);
        }}
        onBlur=${() => {
          setOpen(false);
          if (shown && !input.current.value.trim()) hide(false);
        }}
        onInput=${(e) => {
          setQuery(e.target.value);
          run(e.target.value);
        }}
        onKeyDown=${onKeyDown}
      />
      <ul id="km-search-list" role="listbox" aria-label=${t('search.results')} hidden=${!expanded}>
        ${options.map(
          (o, i) => html`
            <li
              id=${`km-opt-${i}`}
              role="option"
              tabindex="-1"
              aria-selected=${i === active}
              class=${i === active ? 'active' : ''}
              onMouseDown=${(e) => {
                e.preventDefault();
                choose(o);
              }}
              onMouseMove=${() => setActive(i)}
            >
              <span class="opt-label">${o.label}</span>
              <span class="opt-detail">${o.detail}</span>
              <span class="opt-type">${t(`search.type.${o.type}`)}</span>
            </li>
          `,
        )}
      </ul>
      <button
        type="button"
        class="search-close"
        aria-label=${t('search.close')}
        title=${t('search.close')}
        onMouseDown=${(e) => {
          // Focus stays in the box, which an empty box would leave and close.
          e.preventDefault();
        }}
        onClick=${() => hide(true)}
      >
        <${CloseIcon} />
      </button>
      <p id="km-search-status" class="sr-only" aria-live="polite">${status}</p>
    </div>
  `;
}
