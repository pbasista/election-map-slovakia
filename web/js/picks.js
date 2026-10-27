/* The candidates the visitor has circled, as voters circle numbers on the
 * ballot: candidacy ids (data.js, `<contest>#<n>`) in the order circled.
 * app.js keeps them in the URL hash (`k`), so that a link carries them:
 * per contest its id and the numbers circled, joined by dots; the contests
 * joined by commas, in the order the first of each was circled
 * (`oz:528595/3.7.12,starosta:528595.2`). */

// A contest id (data.js `parseContest`): kind, area, and the obvod if any.
const CONTEST = /^(oz|starosta|zsk|predseda):[0-9A-Z]+(\/[1-9]\d*)?$/;
const NUMBER = /^[1-9]\d*$/;

/* Contest id → the numbers circled in it, in ballot order; the contests in
 * the order the first of each was circled. */
export function byContest(picks) {
  const groups = new Map();
  for (const id of picks) {
    const hash = id.lastIndexOf('#');
    const contest = id.slice(0, hash);
    if (!groups.has(contest)) groups.set(contest, []);
    groups.get(contest).push(Number(id.slice(hash + 1)));
  }
  for (const numbers of groups.values()) numbers.sort((a, b) => a - b);
  return groups;
}

export const formatPicks = (picks) =>
  [...byContest(picks)].map(([contest, numbers]) => [contest, ...numbers].join('.')).join(',');

/* The picks hash value *text* names. Anything that is not a contest id or
 * a ballot number (a link cut short, say) is dropped, and so are repeats. */
export function parsePicks(text) {
  const picks = new Set();
  for (const group of (text ?? '').split(',')) {
    const [contest, ...numbers] = group.split('.');
    if (!CONTEST.test(contest)) continue;
    for (const n of numbers) if (NUMBER.test(n)) picks.add(`${contest}#${n}`);
  }
  return [...picks];
}

export const togglePick = (picks, id) => (picks.includes(id) ? picks.filter((x) => x !== id) : [...picks, id]);
