/* Election Map Slovakia: a map of the 2026 Slovak municipal and regional
 * elections, with the candidates on every ballot.
 *
 * The page is the map. Floating on it: the site name with the search, the
 * language, boundaries, theme and Favourites buttons, zoom and help, and
 * while the map shows 2026 results, their legend (mapmode.js). A pane
 * (pane.js) shows a place's ballots or a candidate card. Favourites (the
 * circled candidates) open in a second pane beside it where the screen is
 * wide enough, else in the pane.
 *
 * The selection lives in the URL hash, so a link can be shared and Back and
 * Forward work:
 *   o     obec code
 *   ll    "lat,lon" of the picked point
 *   a     the address shown
 *   n     council obvod, where the obec has several (`n=3~`: taken from the
 *         approximate boundary at a clicked point)
 *   d     okrsok (polling district), where the obec's are drawn (`d=3~`
 *         likewise)
 *   s, p  the street or part of the obec chosen in the search (highlighted)
 *   c     an open candidacy
 *   r     a contest's area shown without a place: a Bratislava or Košice
 *         city contest's or a regional one's (data.js `contestArea`)
 *   f=1   Favourites shown (favourites.js)
 *   v     `about` the About dialog, `about-<section>` one of its sections
 *         (about.js)
 *
 * The visitor's own work is in the hash too, so a link shares it: `k` the
 * circled candidates (picks.js); `fp`, `fm` and `x` the filter, crossed-out
 * candidates included (ballots.js `filterParams`). It changes in place:
 * Back and Forward move between places and leave the circles and the
 * filter alone. Only a link typed or pasted into the address bar brings
 * its own.
 */

import { html, render, useEffect, useRef, useState } from '../vendor/preact-htm.module.js';
import { aboutSection, aboutView } from './about.js';
import { Ballots, filterParams, NO_FILTER, parseFilter } from './ballots.js';
import { CandidateCard } from './candidate.js';
import { FavouritesButton, HelpMenu, LanguageMenu, LayerMenus, ThemeMenu, ZoomButtons } from './controls.js';
import { dataIndex } from './data.js';
import { Favourites } from './favourites.js';
import { election, formatDate, loadStrings, t, translationPending } from './i18n.js';
import { Logo, MoreIcon } from './icons.js';
import { LiveStatus } from './live.js';
import { createMap } from './map.js';
import { MapResults, useMapMode } from './mapmode.js';
import { AboutDialog, Pane, PHONE, WIDE } from './pane.js';
import { formatPicks, parsePicks } from './picks.js';
import { Search } from './search.js';

// The history.state of the site's own entries; a link typed or pasted into
// the address bar makes one without it.
const OWN = { km: true };

const hashParams = () => new URLSearchParams(location.hash.slice(1));

/* A unit number with an approximate mark (`3~`) as [number, approximate]. */
function parseUnit(value) {
  const text = value ?? '';
  return [Number.parseInt(text, 10) || null, text.endsWith('~')];
}

const formatUnit = (n, approximate) => `${n}${approximate ? '~' : ''}`;

function readHash() {
  const p = hashParams();
  const ll = (p.get('ll') ?? '').split(',').map(Number);
  const point = ll.length === 2 && ll.every(Number.isFinite);
  const [obvod, approximate] = parseUnit(p.get('n'));
  const [okrsok, okrsokApproximate] = parseUnit(p.get('d'));
  return {
    obec: p.get('o'),
    lat: point ? ll[0] : null,
    lon: point ? ll[1] : null,
    label: p.get('a'),
    obvod,
    approximate,
    okrsok,
    okrsokApproximate,
    street: p.get('s'),
    part: p.get('p'),
    candidate: p.get('c'),
    view: p.get('v'),
    area: p.get('r'),
    favourites: p.get('f') === '1',
  };
}

/* The visitor's work a link carries: the circled candidates, and the
 * filter's hash values {fp, fm, x} (null without a filter), whose parties
 * can be looked up only once data/index.json has loaded. */
function readWork() {
  const p = hashParams();
  const [fp, fm, x] = [p.get('fp'), p.get('fm'), p.get('x')];
  return { picks: parsePicks(p.get('k')), linked: fp || fm || x ? { fp, fm, x } : null };
}

/* The hash of selection *s* with the circled candidates *picks* and the
 * filter's hash values *filter* ([key, value] pairs). */
function hashOf(s, picks, filter) {
  const p = new URLSearchParams();
  if (s.view) p.set('v', s.view);
  if (s.obec) {
    p.set('o', s.obec);
    if (Number.isFinite(s.lat)) p.set('ll', `${s.lat.toFixed(5)},${s.lon.toFixed(5)}`);
    if (s.label) p.set('a', s.label);
    if (s.obvod) p.set('n', formatUnit(s.obvod, s.approximate));
    if (s.okrsok) p.set('d', formatUnit(s.okrsok, s.okrsokApproximate));
    if (s.street) p.set('s', s.street);
    if (s.part) p.set('p', s.part);
  }
  if (s.candidate) p.set('c', s.candidate);
  if (s.area && !s.obec) p.set('r', s.area);
  if (s.favourites) p.set('f', '1');
  if (picks.length) p.set('k', formatPicks(picks));
  for (const [key, value] of filter) p.set(key, value);
  // Characters a fragment may hold as they are (RFC 3986) read better in a
  // link than percent-encoded; URLSearchParams reads them back either way.
  const hash = p.toString().replace(/%(3A|2F|2C|21|7E)/g, (_, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
  return hash ? `#${hash}` : '';
}

/* Puts *hash* in the address bar as one of the site's own entries: a new
 * entry with *push*, else in place of the current one. */
function writeHash(hash, push = false) {
  const url = hash || location.pathname;
  if (push) history.pushState(OWN, '', url);
  else history.replaceState(OWN, '', url);
}

function App() {
  const [state, setState] = useState(readHash);
  // The constituency overlays and the base map's roads, railways and water
  // (`base`) and buildings switched on (map.js `setOverlays`).
  const [overlays, setOverlays] = useState({
    zsk: true,
    city: true,
    oz: true,
    okrsky: true,
    base: true,
    buildings: true,
  });
  const [mapFailed, setMapFailed] = useState(false);
  const mapElement = useRef(null);
  // The map.js handle, once the map is up.
  const [map, setMap] = useState(null);
  const [zoomLimits, setZoomLimits] = useState({ canZoomIn: true, canZoomOut: true });
  // The open popover: 'language', 'constituencies', 'turnout', 'base',
  // 'theme', 'help' or null.
  const [menu, setMenu] = useState(null);
  const finder = useRef(null);
  const pane = useRef(null);
  const legend = useRef(null);
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
  // Whether the screen has room for Favourites beside the pane (WIDE), and
  // whether it is a phone's, where the pane is a sheet (PHONE).
  const [wide, setWide] = useState(WIDE.matches);
  const [phone, setPhone] = useState(PHONE.matches);
  const beside = wide && state.favourites;
  // The sheet's height (pane.js SNAPS) and the place it is of: a place
  // opened, or another one picked, opens at `half`.
  const [sheet, setSheet] = useState({ place: null, snap: 'half' });
  // The element at the top of the sheet that the legend goes in, on a phone.
  const [sheetTop, setSheetTop] = useState(null);
  // Whether the buttons put away under "more" are out (on a phone with the
  // sheet open).
  const [more, setMore] = useState(false);
  const topControls = useRef(null);
  const mode = useMapMode();
  // The candidates circled (picks.js) and the candidate filter (ballots.js
  // `NO_FILTER`): kept from place to place.
  const [picks, setPicks] = useState(() => readWork().picks);
  const [filter, setFilter] = useState(NO_FILTER);
  // The filter a link names ({fp, fm, x}), until data/index.json has loaded
  // to look up its parties; the address keeps it till then.
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
    writeHash(hash, true);
    setState(readHash());
  }

  // For the map, set up once: navigate as of the latest render, which knows
  // the circles, the filter and whether Favourites are open.
  const latestNavigate = useRef(navigate);
  latestNavigate.current = navigate;

  /* What covers the map, in pixels from each edge: the search card, the
   * pane, the buttons on the right, and on a phone the results' legend
   * under the search card (`legend`, its share of `top`). The map keeps the
   * places it moves to clear of them where there is room (map.js `room`).
   * Layout boxes rather than transformed ones, as the pane may be sliding
   * in; a phone's sheet counts at the height it is heading to (pane.js). */
  function insets() {
    const out = { top: 0, right: 56, bottom: 0, left: 0, legend: 0 };
    const side = finder.current.parentElement;
    const cardBottom = side.offsetTop + finder.current.offsetTop + finder.current.offsetHeight;
    const p = pane.current;
    if (PHONE.matches) {
      out.top = cardBottom;
      if (p) out.bottom = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sheet-height'));
    } else if (p) {
      out.left = side.offsetLeft + p.offsetLeft + p.offsetWidth;
    } else {
      out.top = cardBottom;
    }
    // Under the search card (app.css); with the sheet open, in it. Elsewhere
    // it is a corner of the map, and a band as wide as the map kept clear
    // for it would cost labels.
    const l = legend.current;
    if (l && PHONE.matches) {
      out.legend = Math.max(0, l.offsetTop + l.offsetHeight - out.top);
      out.top += out.legend;
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
        if (hash !== location.hash) writeHash(hash);
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
        setFilter(parseFilter(linked, index.parties));
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
    writeHash(hash);
  }, [picks, filter, linked]);

  useEffect(() => {
    createMap(mapElement.current, {
      onPick: ({ obec, lat, lon, label, obvod, approximate, okrsok, okrsokApproximate }) =>
        latestNavigate.current({ obec, lat, lon, label, obvod, approximate, okrsok, okrsokApproximate }),
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
  }, [map, moves, state.obec, state.lat, state.lon, state.street, state.part, state.obvod, state.okrsok, state.area]);

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
    const onWide = () => setWide(WIDE.matches);
    const onPhone = () => setPhone(PHONE.matches);
    WIDE.addEventListener('change', onWide);
    PHONE.addEventListener('change', onPhone);
    return () => {
      WIDE.removeEventListener('change', onWide);
      PHONE.removeEventListener('change', onPhone);
    };
  }, []);

  // Favourites in a pane of their own beside the left column; on narrower
  // screens they are what the pane shows, unless a card goes over them.
  const inPane = state.favourites && !beside;
  const favouritesShown = beside || (inPane && !state.candidate);
  const paneOpen = Boolean(state.obec || state.candidate || inPane);
  const about = aboutSection(state.view);
  // Focus inside a pane would be lost with it; the map is where it was.
  const releaseFocus = (container) => {
    if (container.current?.contains(document.activeElement)) mapElement.current.focus();
  };
  const closePane = () => {
    releaseFocus(pane);
    navigate({});
  };
  // In the pane: back to the place's ballots, or with no place, it closes.
  const closeFavourites = () => {
    releaseFocus(besidePane);
    if (inPane && !state.obec) closePane();
    else navigate({ ...state, favourites: false });
  };

  const placeKey = paneOpen
    ? [state.obec, state.lat, state.lon, state.obvod, state.okrsok, state.street, state.part].join('|')
    : null;
  const snap = sheet.place === placeKey ? sheet.snap : 'half';
  const setSnap = (next) => setSheet({ place: placeKey, snap: next });
  // Results put on the map from the sheet: the map is what they are for, so
  // the sheet goes down to `peek`, before the map fits them (mapmode.js,
  // which reads the sheet's height through `insets`). Taken off, the sheet
  // stays as it is.
  useEffect(() => {
    if (mode) setSnap('peek');
  }, [mode]);
  // What covers the map has changed.
  useEffect(() => {
    map?.redraw();
  }, [snap]);
  useEffect(() => setMore(false), [paneOpen]);
  // The buttons put away go back on a click elsewhere.
  useEffect(() => {
    if (!more) return undefined;
    const outside = (e) => {
      if (!topControls.current.contains(e.target)) setMore(false);
    };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [more]);

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
  const fitArea = (target) => map?.fitArea(target, true);
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
    onArea=${fitArea}
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
      okrsok=${state.okrsok}
      okrsokApproximate=${state.okrsokApproximate}
      focus=${cardLeft && !cardLeft.favourites ? cardLeft.id : null}
      onCandidate=${openCandidate}
      filter=${filter}
      onFilter=${changeFilter}
      picks=${picks}
      onPicks=${setPicks}
      onArea=${fitArea}
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
          <${LiveStatus} />
        </header>
        ${
          paneOpen
            ? html`<${Pane} paneRef=${pane} onClose=${closePane} snap=${snap} onSnap=${setSnap} topRef=${setSheetTop}>
                ${content}
              <//>`
            : null
        }
      </div>
      ${
        beside
          ? html`<${Pane} paneRef=${besidePane} beside label=${t('favourites.title')} onClose=${closeFavourites}>
              ${favourites}
            <//>`
          : null
      }
      <div
        class=${more ? 'controls top more-open' : 'controls top'}
        ref=${topControls}
        onKeyDown=${(e) => {
          // A popover open closes first (controls.js).
          if (e.key !== 'Escape' || !more || e.defaultPrevented) return;
          e.preventDefault();
          setMore(false);
          topControls.current.querySelector('.controls-more').focus();
        }}
      >
        <button
          type="button"
          class="fab controls-more"
          aria-label=${t('nav.more')}
          title=${t('nav.more')}
          aria-expanded=${more ? 'true' : 'false'}
          aria-controls="km-more"
          onClick=${() => setMore(!more)}
        >
          <${MoreIcon} />
        </button>
        <div class="controls-stack" id="km-more">
          <${LanguageMenu} open=${menu === 'language'} onToggle=${toggle('language')} hash=${link(state)} />
          <${LayerMenus} menu=${menu} toggle=${toggle} overlays=${overlays} onOverlays=${setOverlays} />
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
      <${MapResults}
        map=${map}
        legendRef=${legend}
        phone=${phone}
        sheet=${phone && paneOpen ? sheetTop : null}
        insets=${insets}
      />
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
