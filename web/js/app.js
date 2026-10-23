/* Election Map Slovakia: a map of the constituencies of the 2026 Slovak
 * municipal and regional elections, with the candidates on every ballot.
 *
 * The page is the map. Floating on it: the site name with the search, the
 * language, boundary, theme and Favourites buttons, the zoom buttons and
 * help; a pane with a place's ballots or a candidate card opens where there
 * is something to show, and closes again (pane.js). Favourites (the
 * candidates circled) open in a pane of their own beside it where the
 * screen is wide enough, else in the pane.
 *
 * What is selected lives in the URL hash, so a link can be shared and back
 * and forward work: `o` obec code, `ll` "lat,lon" of the picked point, `a`
 * the address shown, `n` its council obvod where the obec has several (`n=3~`
 * when taken from the approximate boundary at a clicked point), `s` or `p`
 * the street or part of the obec chosen in the search (highlighted on the
 * map), `c` an open candidacy, `r` a contest's area shown on the map
 * without a place (a Bratislava or Košice city contest's, a regional one's:
 * data.js `contestArea`), `f=1` Favourites shown (favourites.js), `v=about`
 * the About dialog (`v=about-<section>` one of its sections, about.js).
 *
 * So does the visitor's own work, so that a link shares it too: `k` the
 * candidates circled (picks.js), `fp` and `fm` the filter (ballots.js
 * `filterParams`). That changes in place: Back and Forward go from place to
 * place, and leave the circles and the filter as they are. Only a link
 * typed or pasted into the address bar brings its own.
 */

import { html, render, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { aboutSection, aboutView } from './about.js';
import { Ballots, filterParams, NO_FILTER, parseFilter } from './ballots.js';
import { CandidateCard } from './candidate.js';
import { FavouritesButton, HelpMenu, LanguageMenu, LayerMenu, ThemeMenu, ZoomButtons } from './controls.js';
import { dataIndex } from './data.js';
import { Favourites } from './favourites.js';
import { election, formatDate, loadStrings, t, translationPending } from './i18n.js';
import { Logo } from './icons.js';
import { createMap } from './map.js';
import { AboutDialog, Pane, PHONE, WIDE } from './pane.js';
import { formatPicks, parsePicks } from './picks.js';
import { Search } from './search.js';

// The history.state of the entries the site makes, which a link typed or
// pasted into the address bar makes without.
const OWN = { km: true };

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const ll = (p.get('ll') ?? '').split(',').map(Number);
  const point = ll.length === 2 && ll.every(Number.isFinite);
  return {
    obec: p.get('o'),
    lat: point ? ll[0] : null,
    lon: point ? ll[1] : null,
    label: p.get('a'),
    obvod: Number.parseInt(p.get('n') ?? '', 10) || null,
    approximate: (p.get('n') ?? '').endsWith('~'),
    street: p.get('s'),
    part: p.get('p'),
    candidate: p.get('c'),
    view: p.get('v'),
    area: p.get('r'),
    favourites: p.get('f') === '1',
  };
}

/* The visitor's work a link carries: the circled candidates, and the
 * filter as its hash values (`fp`, `fm`), whose parties are known only
 * once data/index.json has loaded; null for a filter it has not. */
function readWork() {
  const p = new URLSearchParams(location.hash.slice(1));
  const [fp, fm] = [p.get('fp'), p.get('fm')];
  return { picks: parsePicks(p.get('k')), linked: fp || fm ? { fp, fm } : null };
}

/* The hash of selection *s* with the circled candidates *picks* and the
 * filter's hash values *filter* ([key, value] pairs). */
function hashOf(s, picks, filter) {
  const p = new URLSearchParams();
  if (s.view) p.set('v', s.view);
  if (s.obec) p.set('o', s.obec);
  if (s.obec && Number.isFinite(s.lat)) p.set('ll', `${s.lat.toFixed(5)},${s.lon.toFixed(5)}`);
  if (s.obec && s.label) p.set('a', s.label);
  if (s.obec && s.obvod) p.set('n', `${s.obvod}${s.approximate ? '~' : ''}`);
  if (s.obec && s.street) p.set('s', s.street);
  if (s.obec && s.part) p.set('p', s.part);
  if (s.candidate) p.set('c', s.candidate);
  if (s.area && !s.obec) p.set('r', s.area);
  if (s.favourites) p.set('f', '1');
  if (picks.length) p.set('k', formatPicks(picks));
  for (const [key, value] of filter) p.set(key, value);
  // What a fragment may hold as it is (RFC 3986) reads better in a link
  // than percent-encoded; URLSearchParams reads it back either way.
  const hash = p.toString().replace(/%(3A|2F|2C|21|7E)/g, (_, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
  return hash ? `#${hash}` : '';
}

function App() {
  const [state, setState] = useState(readHash);
  // The constituency overlays switched on (map.js `setOverlays`).
  const [overlays, setOverlays] = useState({ zsk: true, city: true, oz: true });
  const [mapFailed, setMapFailed] = useState(false);
  const mapElement = useRef(null);
  // The map.js handle, once the map is up.
  const [map, setMap] = useState(null);
  const [zoomLimits, setZoomLimits] = useState({ canZoomIn: true, canZoomOut: true });
  // The open popover: 'language', 'layers', 'theme', 'help' or null.
  const [menu, setMenu] = useState(null);
  const finder = useRef(null);
  const pane = useRef(null);
  // How the map should move for the next selection (map.js `select`); a page
  // opened on a shared link goes to the place or area it names.
  const pendingView = useRef(state.obec || state.area ? 'place' : null);
  // Counts requests to move the map, which may name the same place again.
  const [moves, setMoves] = useState(0);
  const ownHash = useRef(location.hash);
  // The candidacy whose card the Back button just left, and whether it was
  // opened from Favourites ({id, favourites}): its row takes the focus.
  const [cardLeft, setCardLeft] = useState(null);
  // Whether the candidate last opened was chosen in Favourites.
  const openedFrom = useRef(false);
  const besidePane = useRef(null);
  // Whether the screen has room for Favourites beside the pane (WIDE).
  const [wide, setWide] = useState(WIDE.matches);
  const beside = wide && state.favourites;
  // The candidates circled (picks.js) and the candidate filter (ballots.js
  // `NO_FILTER`): kept from place to place.
  const [picks, setPicks] = useState(() => readWork().picks);
  const [filter, setFilter] = useState(NO_FILTER);
  // The filter a link names ({fp, fm}), until data/index.json has loaded to
  // look up its parties; the address keeps it till then.
  const [linked, setLinked] = useState(() => readWork().linked);
  const filterHash = linked ? Object.entries(linked).filter(([, value]) => value) : filterParams(filter);
  const link = (s) => hashOf(s, picks, filterHash);
  // The same for the history listener, which is set up once.
  const work = useRef(null);
  work.current = { picks, filterHash };

  const changeFilter = (next) => {
    setLinked(null);
    setFilter(next);
  };

  function navigate(next, view = null) {
    // Beside the pane, Favourites stay open whatever the pane goes to (a map
    // click, a card) unless *next* says: closed with their button, or for a
    // place found by the search or shown by a pin, which they would hide.
    const hash = link(beside && !('favourites' in next) ? { ...next, favourites: true } : next);
    pendingView.current = view;
    setCardLeft(null);
    if (view) setMoves((n) => n + 1);
    if (hash === location.hash) return;
    ownHash.current = hash;
    history.pushState(OWN, '', hash || location.pathname);
    setState(readHash());
  }

  // For the map, set up once: navigate as of the latest render, which knows
  // the circles, the filter and whether Favourites are open.
  const latestNavigate = useRef(navigate);
  latestNavigate.current = navigate;

  /* The pixels of the map that the search card, the pane and the right-hand
   * buttons cover; the map keeps places it moves to out from under them.
   * Layout boxes, not the transformed ones: the pane may be sliding in. */
  function insets() {
    const out = { top: 0, right: 56, bottom: 0, left: 0 };
    const side = finder.current.parentElement;
    const cardBottom = side.offsetTop + finder.current.offsetTop + finder.current.offsetHeight;
    const p = pane.current;
    if (PHONE.matches) {
      out.top = cardBottom;
      // The sheet is fixed to the viewport.
      if (p) out.bottom = innerHeight - p.offsetTop;
    } else if (p) {
      out.left = side.offsetLeft + p.offsetLeft + p.offsetWidth;
    } else {
      out.top = cardBottom;
    }
    return out;
  }

  useEffect(() => {
    // The entry the page opened on is the site's own from now on.
    history.replaceState(OWN, '', location.href);
    const onChange = () => {
      if (location.hash === ownHash.current) return;
      // Back and forward go to the place they come back to.
      pendingView.current = 'place';
      setCardLeft(null);
      setState(readHash());
      if (history.state?.km) {
        // The circles and the filter stay as they are, and the address
        // with them.
        const hash = hashOf(readHash(), work.current.picks, work.current.filterHash);
        if (hash !== location.hash) history.replaceState(OWN, '', hash || location.pathname);
      } else {
        const next = readWork();
        setPicks(next.picks);
        setFilter(NO_FILTER);
        setLinked(next.linked);
        history.replaceState(OWN, '', location.href);
      }
      ownHash.current = location.hash;
    };
    addEventListener('hashchange', onChange);
    addEventListener('popstate', onChange);
    return () => {
      removeEventListener('hashchange', onChange);
      removeEventListener('popstate', onChange);
    };
  }, []);

  useEffect(() => {
    if (!linked) return;
    let live = true;
    dataIndex().then(
      (index) => {
        if (!live) return;
        setFilter(parseFilter(linked.fp, linked.fm, index.parties));
        setLinked(null);
      },
      (e) => console.error(e),
    );
    return () => {
      live = false;
    };
  }, [linked]);

  // The circles and the filter change the address in place.
  useEffect(() => {
    const hash = link(state);
    if (hash === location.hash) return;
    ownHash.current = hash;
    history.replaceState(OWN, '', hash || location.pathname);
  }, [picks, filter, linked]);

  useEffect(() => {
    createMap(mapElement.current, {
      onPick: (p) =>
        latestNavigate.current({
          obec: p.obec,
          lat: p.lat,
          lon: p.lon,
          label: p.label,
          obvod: p.obvod,
          approximate: p.approximate,
        }),
      insets,
      onZoom: setZoomLimits,
    })
      .then(setMap)
      .catch((e) => {
        console.error(e);
        setMapFailed(true);
      });
  }, []);

  useEffect(() => {
    if (!map) return;
    const view = pendingView.current;
    pendingView.current = null;
    map.select(state.obec ? state : state.area ? { area: state.area } : null, view);
  }, [map, moves, state.obec, state.lat, state.lon, state.street, state.part, state.obvod, state.area]);

  useEffect(() => {
    map?.setOverlays(overlays);
  }, [map, overlays]);

  // A chosen street or part is named like an address.
  const label = state.label ?? state.street ?? state.part;

  useEffect(() => {
    document.title = label ? `${label} · ${t('app.title')}` : t('app.title');
  }, [label]);

  // On phones the buttons sit under the search card, whose height varies.
  useEffect(() => {
    const card = finder.current;
    const observer = new ResizeObserver(() =>
      document.documentElement.style.setProperty('--finder-height', `${card.offsetHeight}px`),
    );
    observer.observe(card);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onChange = () => setWide(WIDE.matches);
    WIDE.addEventListener('change', onChange);
    return () => WIDE.removeEventListener('change', onChange);
  }, []);

  // Favourites in a pane of their own beside the left column; on narrower
  // screens they are what the pane shows, unless a card goes over them.
  const inPane = state.favourites && !beside;
  const favouritesShown = beside || (inPane && !state.candidate);
  const paneOpen = Boolean(state.obec || state.candidate || inPane);
  const closePane = () => {
    // Focus inside the pane would be lost with it; the map is where it was.
    if (pane.current?.contains(document.activeElement)) mapElement.current.focus();
    navigate({});
  };
  // In the pane: back to the place's ballots, or with no place, it closes.
  const closeFavourites = () => {
    if (besidePane.current?.contains(document.activeElement)) mapElement.current.focus();
    if (inPane && !state.obec) closePane();
    else navigate({ ...state, favourites: false });
  };

  useEffect(() => {
    const onKey = (e) => {
      // A popover, the dialog and the search box handle their own Esc.
      if (e.key !== 'Escape' || e.defaultPrevented || about !== null || e.target.closest?.('.search')) return;
      if (besidePane.current?.contains(e.target)) closeFavourites();
      else if (paneOpen) closePane();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  const toggle = (name) => (open) => setMenu(open ? name : null);
  const about = aboutSection(state.view);
  const openCandidate = (id, fromFavourites = false) => {
    openedFrom.current = fromFavourites;
    navigate({ ...state, candidate: id, view: null });
  };

  const favourites = html`<${Favourites}
    picks=${picks}
    onPicks=${setPicks}
    filter=${filter}
    onFilter=${changeFilter}
    focus=${cardLeft?.favourites ? cardLeft.id : null}
    onCandidate=${(id) => openCandidate(id, true)}
    onPlace=${({ obec, obvod, area }) =>
      // Beside the pane, or as wide as the page in it above a phone's sheet,
      // Favourites would hide the place shown.
      navigate({ favourites: !beside && PHONE.matches, obec, obvod, area }, 'place')}
    onBack=${beside ? null : closeFavourites}
    link=${`${location.origin}${location.pathname}${link({ favourites: true })}`}
  />`;

  let content = null;
  if (state.candidate) {
    content = html`<${CandidateCard}
      id=${state.candidate}
      onCandidate=${openCandidate}
      filter=${filter}
      onFilter=${changeFilter}
      picks=${picks}
      onPicks=${setPicks}
      onPlace=${({ obec, obvod, area }) =>
        // Beside the pane, Favourites would hide the place on the map.
        navigate({ candidate: state.candidate, favourites: inPane, obec, obvod, area }, 'place')}
      onClose=${() => {
        const left = { id: state.candidate, favourites: openedFrom.current };
        if (!state.obec && !inPane) closePane();
        else navigate({ ...state, candidate: null });
        setCardLeft(left);
      }}
    />`;
  } else if (inPane) {
    content = favourites;
  } else if (state.obec) {
    content = html`<${Ballots}
      code=${state.obec}
      label=${label}
      scope=${{ obvod: state.obvod, street: state.street, part: state.part }}
      approximate=${state.approximate}
      focus=${cardLeft && !cardLeft.favourites ? cardLeft.id : null}
      onCandidate=${openCandidate}
      filter=${filter}
      onFilter=${changeFilter}
      picks=${picks}
      onPicks=${setPicks}
    />`;
  }

  const classes = ['app', paneOpen && 'pane-open', inPane && !state.candidate && 'wide'];

  // The map comes last, under everything (app.css), so that Tab reaches the
  // search and the buttons before it.
  return html`
    <div class=${classes.filter(Boolean).join(' ')}>
      <div class="side">
        <header class="finder float" ref=${finder}>
          <${Search}
            onPlace=${(p, view) =>
              // Favourites beside the pane would hide the place found.
              navigate({ ...p, candidate: null, view: null, favourites: false }, view)}
            onCandidate=${openCandidate}
          >
            <${Logo} />
            <span class="brand-text">
              <span class="brand-name">${t('app.name')}</span>
              <span class="brand-tagline">${t('app.tagline', { date: formatDate(election) })}</span>
            </span>
          <//>
          ${translationPending() ? html`<p class="translation-pending" role="note">${t('translation.pending')}</p>` : null}
        </header>
        ${paneOpen ? html`<${Pane} paneRef=${pane} onClose=${closePane}>${content}<//>` : null}
      </div>
      ${
        beside
          ? html`<${Pane} paneRef=${besidePane} beside label=${t('favourites.title')} onClose=${closeFavourites}>
              ${favourites}
            <//>`
          : null
      }
      <div class="controls top">
        <${LanguageMenu} open=${menu === 'language'} onToggle=${toggle('language')} hash=${link(state)} />
        <${LayerMenu}
          open=${menu === 'layers'}
          onToggle=${toggle('layers')}
          overlays=${overlays}
          onOverlays=${setOverlays}
        />
        <${ThemeMenu} open=${menu === 'theme'} onToggle=${toggle('theme')} />
        <${FavouritesButton}
          count=${picks.length}
          open=${favouritesShown}
          onPress=${() =>
            favouritesShown
              ? closeFavourites()
              : navigate({ ...state, favourites: true, candidate: wide ? state.candidate : null, view: null })}
        />
      </div>
      <div class="controls bottom">
        <${ZoomButtons} map=${map} limits=${zoomLimits} />
        <${HelpMenu}
          open=${menu === 'help'}
          onToggle=${toggle('help')}
          aboutHash=${link({ ...state, view: 'about' })}
          onAbout=${() => {
            setMenu(null);
            navigate({ ...state, view: 'about' });
          }}
        />
      </div>
      <div class="map" ref=${mapElement} role="application" aria-label=${t('map.label')}></div>
      ${mapFailed ? html`<p class="map-error" role="alert">${t('error.load')}</p>` : null}
      ${
        about === null
          ? null
          : html`<${AboutDialog}
              section=${about}
              sectionHash=${(section) => link({ ...state, view: aboutView(section) })}
              onSection=${(section) => navigate({ ...state, view: aboutView(section) })}
              onClose=${() => navigate({ ...state, view: null })}
            />`
      }
    </div>
  `;
}

loadStrings()
  .then(() => render(html`<${App} />`, document.getElementById('root')))
  .catch((e) => {
    console.error(e);
    // The strings did not load, so the shell's localized <title> names the site.
    document.getElementById('root').textContent = `${document.title}: failed to load.`;
  });
