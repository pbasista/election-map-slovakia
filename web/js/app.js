/* Election Map Slovakia: a map of the constituencies of the 2026 Slovak
 * municipal and regional elections, with the candidates on every ballot.
 *
 * The page is the map. Floating on it: the site name with the search, the
 * language, boundary and theme menus, the zoom buttons and help; a pane with
 * a place's ballots or a candidate card opens where there is something to
 * show, and closes again (pane.js).
 *
 * What is selected lives in the URL hash, so a link can be shared and back
 * and forward work: `o` obec code, `ll` "lat,lon" of the picked point, `a`
 * the address shown, `n` its council obvod where the obec has several (`n=3~`
 * when taken from the approximate boundary at a clicked point), `s` or `p`
 * the street or part of the obec chosen in the search (highlighted on the
 * map), `c` an open candidacy, `r` a Bratislava or Košice city contest's
 * area shown on the map without a place (data.js `contestArea`), `v=about`
 * the About dialog (`v=about-<section>` one of its sections, about.js).
 */

import { html, render, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { aboutSection, aboutView } from './about.js';
import { Ballots, NO_FILTER } from './ballots.js';
import { CandidateCard } from './candidate.js';
import { HelpMenu, LanguageMenu, LayerMenu, ThemeMenu, ZoomButtons } from './controls.js';
import { election, formatDate, loadStrings, t, translationPending } from './i18n.js';
import { Logo } from './icons.js';
import { createMap } from './map.js';
import { AboutDialog, Pane, PHONE } from './pane.js';
import { Search } from './search.js';

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
  };
}

function hashOf(s) {
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
  const hash = p.toString();
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
  // opened on a shared link goes to the place it names.
  const pendingView = useRef(state.obec ? 'place' : null);
  // Counts requests to move the map, which may name the same place again.
  const [moves, setMoves] = useState(0);
  const ownHash = useRef(location.hash);
  // The candidacy whose card the Back button just left (Ballots `focus`).
  const [cardLeft, setCardLeft] = useState(null);
  // The candidate filter (ballots.js `NO_FILTER`): kept from place to place.
  const [filter, setFilter] = useState(NO_FILTER);

  function navigate(next, view = null) {
    const hash = hashOf(next);
    pendingView.current = view;
    setCardLeft(null);
    if (view) setMoves((n) => n + 1);
    if (hash === location.hash) return;
    ownHash.current = hash;
    if (hash) location.hash = hash;
    else history.pushState(null, '', location.pathname);
    setState(readHash());
  }

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
    const onChange = () => {
      // Back and forward go to the place they come back to.
      if (location.hash !== ownHash.current) {
        pendingView.current = 'place';
        setCardLeft(null);
      }
      ownHash.current = location.hash;
      setState(readHash());
    };
    addEventListener('hashchange', onChange);
    addEventListener('popstate', onChange);
    return () => {
      removeEventListener('hashchange', onChange);
      removeEventListener('popstate', onChange);
    };
  }, []);

  useEffect(() => {
    createMap(mapElement.current, {
      onPick: (p) =>
        navigate({
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

  const paneOpen = Boolean(state.obec || state.candidate);
  const closePane = () => {
    // Focus inside the pane would be lost with it; the map is where it was.
    if (pane.current?.contains(document.activeElement)) mapElement.current.focus();
    navigate({});
  };

  useEffect(() => {
    const onKey = (e) => {
      // A popover, the dialog and the search box handle their own Esc.
      if (e.key !== 'Escape' || e.defaultPrevented || !paneOpen) return;
      if (about !== null || e.target.closest?.('.search')) return;
      closePane();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  const toggle = (name) => (open) => setMenu(open ? name : null);
  const about = aboutSection(state.view);
  const openCandidate = (id) => navigate({ ...state, candidate: id, view: null });

  let content = null;
  if (state.candidate) {
    content = html`<${CandidateCard}
      id=${state.candidate}
      onCandidate=${openCandidate}
      filter=${filter}
      onFilter=${setFilter}
      onPlace=${({ obec, obvod, area }) => navigate({ candidate: state.candidate, obec, obvod, area }, 'place')}
      onClose=${() => {
        if (!state.obec) {
          closePane();
          return;
        }
        navigate({ ...state, candidate: null });
        setCardLeft(state.candidate);
      }}
    />`;
  } else if (state.obec) {
    content = html`<${Ballots}
      code=${state.obec}
      label=${label}
      scope=${{ obvod: state.obvod, street: state.street, part: state.part }}
      approximate=${state.approximate}
      focus=${cardLeft}
      onCandidate=${openCandidate}
      filter=${filter}
      onFilter=${setFilter}
    />`;
  }

  // The map comes last, under everything (app.css), so that Tab reaches the
  // search and the buttons before it.
  return html`
    <div class=${paneOpen ? 'app pane-open' : 'app'}>
      <div class="side">
        <header class="finder float" ref=${finder}>
          <${Search}
            onPlace=${(p, view) => navigate({ ...p, candidate: null, view: null }, view)}
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
      <div class="controls top">
        <${LanguageMenu} open=${menu === 'language'} onToggle=${toggle('language')} hash=${hashOf(state)} />
        <${LayerMenu}
          open=${menu === 'layers'}
          onToggle=${toggle('layers')}
          overlays=${overlays}
          onOverlays=${setOverlays}
        />
        <${ThemeMenu} open=${menu === 'theme'} onToggle=${toggle('theme')} />
      </div>
      <div class="controls bottom">
        <${ZoomButtons} map=${map} limits=${zoomLimits} />
        <${HelpMenu}
          open=${menu === 'help'}
          onToggle=${toggle('help')}
          aboutHash=${hashOf({ ...state, view: 'about' })}
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
              sectionHash=${(section) => hashOf({ ...state, view: aboutView(section) })}
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
