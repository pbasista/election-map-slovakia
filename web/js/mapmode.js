/* The 2026 results on the map: one candidate's share of the votes across
 * the areas of their contest, or the turnout of the municipal or of the
 * regional elections across the country. The map colours the land by it
 * in STEPS intensities of the results' green (draw.js `setResults`), the
 * scale fitted to the values shown so that their differences show, and a
 * legend floats on the map with the scale and a close button.
 *
 * What is shown (the mode) is one for the page, chosen in a candidate's
 * row (`MapButton`) or in the boundaries menu (controls.js), so it lives
 * here rather than being passed down through the panes. The values come
 * from the live results (live.js), and follow them: a contest's `areas`
 * (an obec or city district each, or on election night a regional obvod
 * `obvod:<n>` of the kraj), else the contest's own figures over its own
 * area (a mayor's obec, a council's obec or council obvod, a regional
 * obvod, a kraj's obvody); the turnout of the municipal elections from the
 * mayoral (else council) contests of every municipality and city
 * district, that of Bratislava's and Košice's own elections likewise from
 * theirs, that of the regional
 * ones from each kraj's presidential contest. Below the zoom of the obce
 * the map shows the regional obvody, each by its obce together, unless the
 * contest is of one obec, which would colour a whole obvod by it. */

import { html, useEffect, useMemo, useState } from '../vendor/preact-htm.module.js';
import { contestArea, dataIndex, displayName, useLoaded } from './data.js';
import { formatNumber, formatPercent, t } from './i18n.js';
import { CloseIcon, MapPinIcon } from './icons.js';
import { NOT_COUNTED, useLive } from './live.js';

/* The intensities of the colour: app.css `--map-result-<n>` for a
 * candidate's votes, a turnout's tone mixed into the land (draw.js
 * `TONE_STEPS`, app.css `.map-legend.toned`). */
export const STEPS = 6;
// Values beyond these quantiles (where there are enough to tell) take the
// end steps, so that a hamlet of a dozen voters does not stretch the scale.
const TRIM = 0.05;
const TRIM_FROM = 20;

/* What the map shows: null, {kind: 'candidate', id, contest, number, name,
 * label, multi} (a candidacy, its contest's id and label, `multi` a
 * council), {kind: 'turnout', election: 'municipal' | 'city' |
 * 'regional'} (the city one Bratislava's and Košice's own elections) or
 * {kind: 'turnout', contest, label}: one contest's (ContestMapButton). */
let mode = null;
const listeners = new Set();

export function setMapMode(next) {
  mode = next;
  for (const listener of listeners) listener();
}

/* The mode, for a component: renders it again when it changes. */
export function useMapMode() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((n) => n + 1);
    listeners.add(listener);
    return () => listeners.delete(listener);
  }, []);
  return mode;
}

/* The button at the end of counted candidate *c*'s row (ballots.js) that
 * shows their votes on the map, or takes them off it: across the areas of
 * their contest where it has several, else over its one area. */
export function MapButton({ candidate: c }) {
  const current = useMapMode();
  const on = current?.kind === 'candidate' && current.id === c.id;
  const label = t(on ? 'mapmode.candidate_hide' : 'mapmode.candidate_show');
  const next = {
    kind: 'candidate',
    id: c.id,
    contest: c.contest,
    number: c.number,
    name: displayName(c),
    label: c.result.contestLabel,
    multi: c.result.multi,
  };
  return html`<button
    type="button"
    class="votes-map"
    aria-pressed=${on ? 'true' : 'false'}
    title=${label}
    aria-label=${label}
    onClick=${() => setMapMode(on ? null : next)}
  >
    <${MapPinIcon} />
  </button>`;
}

/* The colour the map shows mode *m* in (draw.js `setResults`): a
 * candidate's votes in the results' green, like the medal; a turnout in the
 * colour its area is drawn in otherwise (app.css `--map-<tone>`), so that
 * nothing changes colour unexpectedly: a municipality's red, a council
 * obvod's orange, Bratislava's and Košice's green, a regional contest's
 * violet. The turnout across the country of the municipal elections is
 * the municipalities', that of the two cities' own elections theirs. */
export function toneOf(m, index) {
  if (m.kind === 'candidate') return 'result';
  if (!m.contest) return { municipal: 'accent', city: 'city', regional: 'zsk' }[m.election];
  const [kind, area] = m.contest.split(':');
  const code = area.split('/')[0];
  if (kind === 'predseda' || kind === 'zsk') return 'zsk';
  if (code === 'BA' || code === 'KE') return 'city';
  return kind === 'oz' && (index?.obce[code]?.[4] ?? 0) > 1 ? 'council' : 'accent';
}

/* The pin at the end of a contest's header (ballots.js `Contest`). A press
 * shows the contest's area on the map (*map* {label, onClick}); once the
 * contest is counted (*counted*), the next press colours that area by the
 * 2026 turnout, in the area's own colour (`toneOf`), and the one after
 * takes it off again; the pin is filled in that colour meanwhile. */
export function ContestMapButton({ contest, map, counted }) {
  const current = useMapMode();
  const [index] = useLoaded(dataIndex, []);
  const [placed, setPlaced] = useState(false);
  const on = current?.kind === 'turnout' && current.contest === contest.id;
  const turnout = !on && placed && counted;
  const label = on ? t('mapmode.contest_turnout_hide') : turnout ? t('mapmode.contest_turnout_show') : map.label;
  const mode = { kind: 'turnout', contest: contest.id, label: contest.label };
  const press = () => {
    if (on) setMapMode(null);
    else if (turnout) setMapMode(mode);
    else {
      map.onClick();
      setPlaced(true);
    }
  };
  return html`<button
    type="button"
    class="contest-map"
    style=${{ '--tone': `var(--map-${toneOf(mode, index)})` }}
    aria-pressed=${counted ? String(on) : undefined}
    title=${label}
    aria-label=${label}
    onClick=${press}
  >
    <${MapPinIcon} />
  </button>`;
}

/* The area files of the municipal elections: every okres's, whose
 * municipalities and city districts elect a mayor and council each. */
const municipalFile = (name) => name.startsWith('okres/');

/* What the figures of *m* are taken from, as live.js has it now: the
 * contest's entry, or the contests of each area file of the election that
 * has loaded. Their identities change exactly when the figures may. */
function sourcesOf(m, live) {
  if (m.kind === 'candidate' || m.contest) {
    const entry = live.of(m.contest);
    return entry && entry !== NOT_COUNTED ? [entry] : [];
  }
  const wanted = {
    municipal: municipalFile,
    city: (name) => name.startsWith('city/'),
    regional: (name) => name.startsWith('kraj/'),
  }[m.election];
  return Object.keys(live.status?.files ?? {})
    .filter(wanted)
    .map((name) => live.contests(name))
    .filter(Boolean);
}

/* Adds [*part*, *whole*] to the sum under *key* in *sums*. */
function add(sums, key, part, whole) {
  const sum = sums.get(key);
  if (sum) {
    sum[0] += part;
    sum[1] += whole;
  } else {
    sums.set(key, [part, whole]);
  }
}

/* The figures of mode *m* from *sources* (`sourcesOf`): [part, whole] —
 * [votes, valid] of a candidate, [voters, eligible] of a turnout — by obec
 * code (`obce`), by regional obvod '<kraj>/<n>' known only as a whole
 * (`whole`), by municipal council obvod '<obec>/<n>' (`councils`), and of
 * all counted (`total`, null if unknown); `local` where the contest is of
 * one obec. */
function figures(m, sources, index) {
  const obce = new Map();
  const whole = new Map();
  const councils = new Map();
  let total = null;
  let local = false;
  // An area of the live results: an obec, or `obvod:<n>` of *kraj*.
  const put = (key, kraj, part, all) => {
    if (key.startsWith('obvod:')) whole.set(`${kraj}/${key.slice('obvod:'.length)}`, [part, all]);
    else if (index.obce[key]) obce.set(key, [part, all]);
  };
  // Every regional obvod of *kraj* as a whole.
  const wholeKraj = (kraj, fig) => {
    for (const [, , k, n] of Object.values(index.obce)) if (k === kraj) whole.set(`${kraj}/${n}`, fig);
  };
  if (m.kind === 'candidate' || m.contest) {
    const [entry] = sources;
    const [kind, area] = m.contest.split(':');
    const code = area.split('/')[0];
    const areas = Object.entries(entry?.areas ?? {});
    // An area's [eligible, voters, valid, votes] as the figures shown.
    const of =
      m.kind === 'candidate'
        ? ([, , valid, votes]) => (valid ? [votes[m.number] ?? 0, valid] : null)
        : ([eligible, voters]) => (eligible && voters != null ? [voters, eligible] : null);
    for (const [key, a] of areas) {
      const fig = of(a);
      if (fig) put(key, code, ...fig);
    }
    if (m.kind === 'candidate') {
      const own = entry?.candidates.find(([n]) => n === m.number);
      if (own && entry.valid) total = [own[1], entry.valid];
    } else if (entry?.eligible && entry.voters != null) {
      total = [entry.voters, entry.eligible];
    }
    // Without areas, the contest's own area: a city's contest its districts
    // (a city council obvod's those in it), which are obce, the city not.
    const city = code === 'BA' || code === 'KE';
    local = (kind === 'starosta' || kind === 'oz') && !city && Boolean(index.obce[code]);
    if (!areas.length && total) {
      if (kind === 'predseda') wholeKraj(code, total);
      else if (kind === 'zsk') whole.set(area, total);
      else if (city) {
        const obvod = kind === 'oz' ? Number(area.split('/')[1]) : null;
        for (const [k, row] of Object.entries(index.obce)) {
          if (row[5] === code && (obvod === null || row[6] === obvod)) obce.set(k, total);
        }
      } else if (local && kind === 'oz' && (index.obce[code][4] ?? 0) > 1) councils.set(area, total);
      else if (local) obce.set(code, total);
    }
  } else if (m.election === 'municipal' || m.election === 'city') {
    // A municipality's turnout is its mayor's contest's; where that has
    // none (a contest not held, or without its figures yet), its council
    // obvody's together. Bratislava's and Košice's districts are
    // municipalities here, electing their own. The two cities' own
    // elections, of a city mayor and council over all their districts, are
    // on ballots of their own, so a layer of their own ('city', from the
    // city files): by district where the mayor's contest has `areas`, else
    // the whole city alike.
    const mayors = new Map();
    const councils = new Map();
    for (const contests of sources) {
      for (const [id, e] of Object.entries(contests)) {
        if (!e.eligible || e.voters == null) continue;
        const [kind, area] = id.split(':');
        const code = area.split('/')[0];
        if (!index.obce[code]) continue;
        if (kind === 'starosta') mayors.set(code, e);
        else if (kind === 'oz') add(councils, code, e.voters, e.eligible);
      }
    }
    const units = new Map(councils);
    for (const [code, e] of mayors) units.set(code, [e.voters, e.eligible]);
    for (const [code, fig] of units) {
      const areas = Object.entries(mayors.get(code)?.areas ?? {});
      if (m.election === 'municipal') obce.set(code, fig);
      else if (areas.length) {
        for (const [key, [eligible, voters]] of areas) if (eligible && voters != null) put(key, null, voters, eligible);
      } else {
        for (const [k, row] of Object.entries(index.obce)) if (row[5] === code) obce.set(k, fig);
      }
    }
    if (units.size) {
      total = [0, 0];
      for (const [part, all] of units.values()) {
        total[0] += part;
        total[1] += all;
      }
    }
  } else {
    for (const contests of sources) {
      const [id, e] = Object.entries(contests).find(([key]) => key.startsWith('predseda:')) ?? [];
      if (!e?.eligible || e.voters == null) continue;
      const kraj = id.slice('predseda:'.length);
      total = total ? [total[0] + e.voters, total[1] + e.eligible] : [e.voters, e.eligible];
      const areas = Object.entries(e.areas ?? {});
      for (const [key, [eligible, voters]] of areas) if (eligible && voters != null) put(key, kraj, voters, eligible);
      // Without areas, the kraj as a whole: each of its obvody.
      if (!areas.length) wholeKraj(kraj, [e.voters, e.eligible]);
    }
  }
  return { obce, whole, councils, total, local };
}

/* What the map and the legend show of *figs* (`figures`): {shown} as
 * draw.js `setResults` takes it, {scale} [low, high] the shares of the
 * lowest and highest step, `below`/`above` whether values lie beyond
 * them, `digits` of the percentages; null with no values. The scale spans
 * the values shown, not from zero: areas not counted yet have none and are
 * left uncoloured, so they do not widen it. */
function present(figs, index) {
  const share = ([part, all]) => part / all;
  const values = [...figs.obce.values(), ...figs.whole.values(), ...figs.councils.values()].map(share).sort((a, b) => a - b);
  if (!values.length) return null;
  const trim = values.length >= TRIM_FROM ? TRIM : 0;
  const quantile = (q) => values[Math.min(values.length - 1, Math.floor(q * values.length))];
  // Whole percentage points, so that the ends read plainly.
  let low = Math.floor(quantile(trim) * 100 + 1e-9) / 100;
  let high = Math.ceil(quantile(1 - trim) * 100 - 1e-9) / 100;
  if (high <= low) {
    if (low >= 1) low = 0.99;
    else high = low + 0.01;
  }
  const digits = high < 0.1 ? 1 : 0;
  // All values alike (a single area, say), there is nothing to tell apart:
  // the strongest step, so that the area shows.
  const alike = values[0] === values.at(-1);
  const step = (v) =>
    alike ? STEPS - 1 : Math.min(STEPS - 1, Math.max(0, Math.floor(((v - low) / (high - low)) * STEPS)));
  const cell = (fig) => [step(share(fig)), formatPercent(share(fig), digits)];
  // The regional obvody by their obce together, for below the obce's zoom
  // (not by a single obec's contest); those known only as a whole as they
  // are.
  const sums = new Map();
  for (const [code, [part, all]] of figs.local ? [] : figs.obce) {
    const [, , kraj, zsk] = index.obce[code];
    add(sums, `${kraj}/${zsk}`, part, all);
  }
  const zsk = Object.fromEntries([...sums].map(([key, fig]) => [key, cell(fig)]));
  for (const [key, fig] of figs.whole) zsk[key] = [...cell(fig), 1];
  return {
    shown: {
      steps: STEPS,
      obce: Object.fromEntries([...figs.obce].map(([code, fig]) => [code, cell(fig)])),
      zsk,
      councils: Object.fromEntries([...figs.councils].map(([key, fig]) => [key, cell(fig)])),
    },
    scale: [low, high],
    below: values[0] < low,
    above: values.at(-1) > high,
    digits,
  };
}

/* Shows the mode on *map* (map.js) and its legend: what is shown, the scale
 * and the share or turnout of all counted. A candidate's votes, or one
 * contest's turnout, have the map fitted to the contest's area.
 * *legendRef* gets the legend's element (app.js `insets`). */
export function MapResults({ map, legendRef }) {
  const m = useMapMode();
  const live = useLive();
  const [index] = useLoaded(dataIndex, []);
  const sources = m && index ? sourcesOf(m, live) : [];
  const tone = m ? toneOf(m, index) : 'result';
  const shown = useMemo(() => {
    if (!m || !index) return null;
    const figs = figures(m, sources, index);
    const p = present(figs, index);
    return { ...p, shown: p && { ...p.shown, tone }, total: figs.total };
  }, [m, index, ...sources]);

  useEffect(() => {
    map?.setResults(shown?.shown ?? null);
  }, [map, shown]);

  useEffect(() => {
    if (map && index && m?.contest) map.fitArea(contestArea(m.contest, index));
  }, [map, index, m]);

  if (!m) return null;
  const percent = (share) => formatPercent(share, shown?.digits ?? 0);
  let title;
  let subtitle;
  let total = null;
  const sum = shown?.total;
  if (m.kind === 'candidate') {
    title = m.name;
    subtitle = `${m.label} · ${t(m.multi ? 'mapmode.share_voters' : 'mapmode.share_valid')}`;
    if (sum) total = `${formatPercent(sum[0] / sum[1])} · ${t('results.votes', { n: formatNumber(sum[0]) })}`;
  } else if (m.contest) {
    title = t('mapmode.turnout_title');
    subtitle = `${m.label} · ${t('mapmode.turnout_of')}`;
    if (sum?.[1]) total = t('mapmode.turnout_total', { turnout: formatPercent(sum[0] / sum[1]) });
  } else {
    title = t(`mapmode.turnout_${m.election}`);
    subtitle = t('mapmode.turnout_by');
    if (sum?.[1]) total = t('mapmode.turnout_total', { turnout: formatPercent(sum[0] / sum[1]) });
  }
  const scale = shown?.scale;
  return html`
    <section
      class=${tone === 'result' ? 'map-legend float' : 'map-legend float toned'}
      style=${{ '--tone': `var(--map-${tone})` }}
      ref=${legendRef}
      aria-label=${t('mapmode.legend')}
    >
      <div class="map-legend-head">
        <p class="map-legend-title"><strong>${title}</strong><span>${subtitle}</span></p>
        <button
          type="button"
          class="map-legend-close"
          title=${t('mapmode.close')}
          aria-label=${t('mapmode.close')}
          onClick=${() => setMapMode(null)}
        >
          <${CloseIcon} />
        </button>
      </div>
      ${
        scale
          ? html`
              <div class="map-legend-scale" aria-hidden="true">
                ${Array.from({ length: STEPS }, (_, i) => html`<span class=${`step-${i + 1}`}></span>`)}
              </div>
              <p class="map-legend-ends">
                <span>${shown.below ? `≤ ${percent(scale[0])}` : percent(scale[0])}</span>
                ${total ? html`<span class="map-legend-total">${total}</span>` : null}
                <span>${shown.above ? `≥ ${percent(scale[1])}` : percent(scale[1])}</span>
              </p>
            `
          : html`<p class="map-legend-none">${t('mapmode.none')}</p>`
      }
    </section>
  `;
}
