# Results

The app shows the results of the elections:
the definitive ones of every kind,
and on the night of a municipal and regional election
(24–25 October 2026) the count as it goes.

They come in two kinds, in the same format ([Files](#files)),
one directory per election, keyed by its day, each kind apart:

- **The final results**, `data/build/<election day>/results/`,
  are written only by the `results` step of `ems make`,
  from the election's pinned definitive packages
  ([Final results as inputs](#final-results-as-inputs));
  without them the directory is absent.
  `ems build` copies it to `dist/results/<election day>/`,
  the results part, which a release deploys
  to the Pages project `results_project`, served at `results_url`
  (`config/site.toml`).
- **The live results** of an election night,
  `data/build/<election day>/live/`,
  are written only by `ems results poll` (and `fake`, for testing).
  `ems results deploy` (and `poll --deploy`) copies them to
  `dist/live/<election day>/`, the live part,
  and deploys it to the Pages project `live_project`, served at `live_url`;
  a release never does.
  They never touch the final results, the `results` step or a release.
  `ems build` copies them too, for `ems serve`.

The app reads the final results
(`status.json` there and the files it names, `web/js/live.js`;
the address is `results` in the app shells' config).
Where there are none yet, an election with `live` in `config/elections.toml`
reads its live results instead (the address `live`),
every minute within its live window,
and switches to the final results as soon as a release brings them.

A later election gets directories of its own and leaves these as they are.
The code is `src/election_map_slovakia/results.py`.

## Commands

```sh
uv run ems results poll                 # every 60 s: volbysr.sk → the live results
uv run ems results poll --deploy        # … and deploy them after every change
uv run ems results poll --once          # one poll, e.g. to try it
uv run ems results fake mid             # dummy live results: none, early, mid, late, final
uv run ems results deploy               # upload the live results to Cloudflare Pages, asks first
```

- `poll` and `fake` write the live results of the election
  `--election DAY` names (its day or slug;
  default: the latest, the newest regular election),
  or the directory given with `--dir`,
  and read its `data/build/<election day>/` (`ems make` first).
  They never write the final results
  nor make the `results` step of `ems make` run again.
  `poll --interval` sets the seconds between polls (default 60);
  `fake --seed` the random seed (default 0).
- `poll` reads volbysr.sk's night files of a municipal and regional
  election only; for any other kind it fails:
  their results come from their inputs.
- `deploy` writes the live part, `dist/live/`
  (the live results of every election that has some),
  shows what each election's hold (phase, version, counts),
  checks them against the [format](#the-votes-add-up)
  and deploys the part alone to `live_project`
  as a production deployment after asking (`--yes`: without).
  Live results that break the contract are not deployed.
  `poll --deploy` does the same after every change, the check included.
  The live part has no key:
  the deployment's commit message names the version
  of each election's live results (`live <day>@<version> …`).
  The final results, the app and the bundles stay as they are.
  It does not run `ems check`, which takes longer; a release does.
- `ems serve` serves the final results at `/results/`
  and the live results at `/live/`, with the rest of the site
  (as `ems build` wrote them).

## Final results as inputs

Once published, the definitive results are pinned in `config/inputs.toml`
like every other input
and named as the election's `results` in `config/elections.toml`,
in the `format` of its kind:

| Kind | `format` | Inputs |
|---|---|---|
| `municipal-regional` | `volbysr` (2026 on), `susr` (2022, 2018, 2017) | `results-oso<year>`, `results-osk<year>`, the year of the election day; with `susr`, the packages its `susr` candidates name, in their order (2018: `oso`, `okrsky`; 2017: `osk`) |
| `by-election` | `susr-by` | the day's package, `results-oso<yyyymm>` |
| `presidential` | `volbysr` | round 1's package, then round 2's |
| `referendum`, `parliament`, `european` | `volbysr` | the package, or its table files |

They are stored in the input store like every other pinned input.
For 2026 both are pinned: the site shows the definitive results.

- **The `results` step of `ems make`** writes the election's final results
  from them, in place of what the directory held,
  as of the packages' newest data (`updated`, `version`),
  and only if they keep the [contract](#the-votes-add-up).
  So a release's results are, like every other file of the site,
  a pure function of its inputs and the same on every machine.
  Without them configured the election has no final results
  (no directory).
- **Nothing else writes them.**
  `poll` and `fake` write the live results, apart,
  so the step's output, its stamp and its record
  stay those of the inputs,
  and a release never carries dummy or night results.

## Testing the app with dummy results

```sh
uv run ems results fake mid             # or none, early, late, final; --seed N
EMS_RESULTS_ANYTIME=1 uv run ems build
uv run ems serve
```

A build with `EMS_RESULTS_ANYTIME=1` reads the live results
every minute at any time, of every election;
otherwise the app reads them only as `live` in elections.toml allows
([deploy.md](deploy.md#results)).
It reads them only where the election has no final results:
to try them on an election with final results,
move its `data/build/<election day>/results/` aside before `ems build`
and back afterwards
(a missing output makes the next `ems make` write it again).
Driving it in a headless browser is in [testing.md](testing.md).

`fake` replaces the election's live results, never its final ones
(`--dir` writes elsewhere, where the site does not look).
It reads the election's list of okrsky (its `units`, 2026's
`units-oso2026`) from `data/raw/` (`ems fetch`);
an election without `units` gets no okrsky.
Remove `data/build/<election day>/live/` once done,
so that no `ems results deploy` ships the dummy results.

### Stages

`fake` writes plausible results of the counting at a stage.
Of a municipal and regional election (a by-election alike,
of its contests):

| Stage | What is counted |
|---|---|
| `none` | polls closed, nothing counted |
| `early` | regional ~10 %, no municipal |
| `mid` | regional ~60 %, ~40 % of the municipalities with their winners, the Bratislava and Košice mayors ~50 % |
| `late` | everything counted, municipal winners only, regional and city mayors still partial |
| `final` | definitive: all candidates, flags, `areas` per municipality, and the okrsok files |

- At night the regional contests have `areas`
  for the municipalities counted, the president's also per obvod.
- Turnout follows each area's last election,
  votes a stable random distribution;
  the counted parts only grow from stage to stage (same seed).
- The first kraj's president race stays too close to call to the end.
- The regional obvod with the fewest voters is fully counted by `mid`
  with a landslide that decides it under the app's rule:
  the uncounted voters are at most
  `max(ceil(1.1 × eligible in 2022), counted eligible) − counted eligible`;
  a candidate is sure of a seat
  when fewer than `seats` others could still reach their votes.
- The okrsky of `final`:
  as many per municipality as `units-oso2026` has;
  a council obvod's those of its rule set where it gives them
  (none for an obvod of a council of several whose rule set does not;
  a council of one obvod has all of the municipality's).
  The figures are split at random so that they add up to the contest's
  and keep to the [check](#the-votes-add-up)
  (a mayor's or president's votes are each unit's valid ballots);
  most municipalities of several okrsky have a made-up `past`
  in the shape below.

Of a country-wide election
(`national.fake`, in `src/election_map_slovakia/national.py`):

- the municipalities are counted by the stage's regional share,
  from 22:00 of the election day (round 2 on its own day);
- a presidential election's round 1 elects nobody,
  its two best go on (flag 2) to round 2, which elects one;
  with a round 2, round 1 is final at every stage after `none`;
- a referendum's last question falls short of its quorum;
- a party-list election's seats go by largest remainder
  among the parties over their threshold, at most a list's size,
  its persons' preference votes lean to the top of the list,
  and its elected are the seats taken by those over the quota first,
  then in list order;
  seats and flags only at `final`;
- `final` has `areas` per municipality
  and the okrsok files where `units` give okrsky
  (a party's list too, its preference votes dealt okrsok by okrsok
  within the party's votes there, its municipalities' their okrsky summed),
  without a made-up `past`.

### On Cloudflare

Fake results must never reach the live results' production deployment.
To try them on Cloudflare, deploy the live part to a preview branch,
which Pages serves at an address of its own:

```sh
uv run ems results fake mid
EMS_RESULTS_ANYTIME=1 uv run ems build
npx wrangler pages deploy dist/live --project-name=ems-live --branch=test
rm -r data/build/<election day>/live    # the dummy results gone
```

## A future election night

The live results are deployed on their own:
each change is a production deployment of the live part
(`live_project`), built locally,
while the app, the bundles and the final results
stay as the last release left them.
The election has no final results until its definitive packages are
pinned, so the app reads the live ones;
a release on the night (of the app, of research, of anything)
deploys no live results and leaves them as they are.
The deployment needs Wrangler set up once: `npx wrangler login`,
or `CLOUDFLARE_API_TOKEN` (permission "Cloudflare Pages: Edit")
and `CLOUDFLARE_ACCOUNT_ID`,
and the live project with its domain `live_url`
(`ems data projects --create`, [deploy.md](deploy.md#setup-once)).
The app must have been released with `live = true` for the election
in `config/elections.toml` before the night
([deploy.md](deploy.md#results)):
the night's deployments change only the live results,
not the app that reads them.

1. **Before the polls close:** `uv run ems results poll --once`;
   it should end with phase `none`,
   and the election's live results directory has `status.json`.
   Run `uv run ems results deploy` once,
   so that `live_url` answers `<day>/status.json`.
2. **The first real files.**
   The meanings of the night files' columns are inferred
   from the 2026 site's scripts and the samples of earlier elections
   (constants at the top of `results.py`).
   So start with `uv run ems results poll`, without deploying.
   When the first regional figures appear (about 21:00 in 2022),
   compare a few contests of the live results directory with volbysr.sk,
   then `uv run ems results deploy`.
3. **Once they match:** `uv run ems results poll --deploy`.
   It fetches the progress files every interval
   and the rest only when they changed,
   rewrites the live results only when their content changed,
   and then writes the live part, checks it and deploys it.
   - Keep the machine awake and online.
   - Every file it fetched is kept under `data/raw/results/<UTC time>/`,
     so a problem found later can be replayed.
   - It logs what it skipped: files still missing (404), unexpected data,
     a municipality's elected mayor whose name fits no single candidate;
     and a deployment it refused, naming what broke the contract.
   - If something goes wrong, stop it: the last deployment stays up.
4. **The clock change.**
   The night ends in the timestamps' clock change
   (03:00 CEST becomes 02:00 CET);
   `poll` keeps ŠÚ SR's times with their offset.
5. **The definitive results.**
   In 2022 they were published the next day around noon,
   when the site switched to "Definitívne výsledky";
   `poll` makes the municipal contests final
   once every municipality is counted.
   In 2026 the CSV packages came with them,
   the regional at 04:09 and the municipal at 12:04 on 25 October
   (in 2022 a week later):
   once both are out, stop `poll`.
   The live results stay deployed as they are
   until the release of step 6 brings the final results.
6. **Pin the packages and release:**
   add `results-oso<year>` and `results-osk<year>` to `config/inputs.toml`
   (their URLs on volbysr.sk, as for 2026)
   and name them as the election's `results` in `config/elections.toml`,
   `uv run ems inputs update results-oso<year> results-osk<year>`
   to download and pin them (sha256, retrieved),
   `uv run ems inputs publish` to put them in the input store,
   `uv run ems make`, whose `results` step writes the final results
   (a package that breaks the contract stops it, naming the units),
   `uv run ems data lock`, commit and release:
   the new results key makes the release deploy the final results,
   from then on every release carries them,
   and the app reads them in place of the live ones,
   a page left open too.
   Turn `live` off in that release;
   the live part stays deployed, read no more.

## Files

All JSON, UTF-8, compact.

- **Area files.**
  An area file has the same name as the main site's area file
  of its contests, without `data/` (`contests.area_name`):
  `okres/<okres>`, `city/BA`, `city/KE`, `kraj/<1-8>`,
  `country` (the country-wide contests)
  and `list/<p>` (party number p's list).
- **Okrsok files.**
  With the final results each has an okrsok file beside it,
  `okrsky/<area>` (`okrsky/okres/101`, `okrsky/city/BA`, `okrsky/kraj/1`);
  the country-wide contests' are by kraj, `okrsky/country/<kraj>`,
  and so are a party's list's, `okrsky/list/<p>/<kraj>`.
- **The turnout file**, `turnout`
  ([below](#turnoutjson)),
  where the municipal, the two cities' or the regional contests
  have a turnout.

### `status.json`

```json
{
  "version": "20261024T214000-3f2a",
  "updated": "2026-10-24T21:40:12+02:00",
  "phase": "partial",
  "source": {
    "osk": {"time": "2026-10-24T21:40:00+02:00", "counted": [612, 6010], "unit": "okrsky",
      "voters": [402118, 4398210]},
    "oso": {"time": "2026-10-24T21:40:00+02:00", "counted": [0, 2921], "unit": "obce",
      "voters": [0, 4401237]}
  },
  "files": {"kraj/1": "a1b2c3d4", "okres/101": "…", "okrsky/kraj/1": "…"}
}
```

- `source` has an entry per source of the election's contests
  (`contests.source_of`), no other:
  `oso` (mayors, councils), `osk` (regional),
  `prez1`, `prez2` (a presidential round), `ref`, `nrsr`, `ep`.
  Its `unit` is `obce` for `oso`, `okrsky` for the others.
- `phase`: `none` (nothing counted yet), `partial` (election night),
  `final` (definitive results of every source of the election).
- `version` changes whenever phase, sources or any file does;
  a run that changes nothing writes nothing.
- `files` maps every area and okrsok file, and the turnout file,
  to the first 8 hex digits of the SHA-256 of its content;
  the app fetches `<day>/<file>.json?v=<hash>`
  from the directory of the `status.json` that lists it
  (`/results/` or `/live/`).
- `source.*.time`: ŠÚ SR's time of the data, ISO 8601 with its offset
  (ŠÚ SR writes SELČ/CEST or SEČ/CET after the time;
  the clocks go back at 03:00 on 25 October).
- `counted`: [units processed, units total], null when unknown.
- `voters`: [registered voters of the units counted, of all units],
  null when unknown (`poll` and `fake`; the final results are complete).
  A unit is, of a regular election, a kraj's president;
  a municipality's mayor, or else its council,
  Bratislava's and Košice's districts rather than the cities.
  - A unit counts whole once it is in, however many voted there.
  - One partly counted counts with the registered voters
    of its okrsky counted,
    of as many as at its last election or as counted, if more.
  - One not counted yet counts with those of its last election.

  The app shows how far the count has got by these,
  under 100 % until every unit is in,
  and by `counted` where they are null;
  in tenths below 10 % and never as 0 % once anything is counted,
  as the small municipalities, counted first,
  are a fraction of a per cent of the voters.

### `<area>.json`

```json
{"contests": {
  "predseda:1": {
    "status": "partial", "counted": [312, 1002],
    "eligible": 288104, "voters": 101233, "valid": 99812,
    "seats": 1, "filled": null,
    "candidates": [[1, 40211, null], [2, 31877, null]],
    "areas": {"obvod:3": [52110, 18001, 17760, {"1": 9001, "2": 6100}]}
  },
  "starosta:500011": {"status": "winner", "counted": null, "eligible": 66697,
    "voters": 26953, "valid": 26100, "seats": 1, "filled": 1,
    "candidates": [[2, 14100, 1]]},
  "oz:500011/1": {"status": "winner", "counted": null, "eligible": null,
    "voters": null, "valid": null, "seats": 2, "filled": 2, "candidates": []}
}}
```

- `status`:
  - `partial`: counting in progress,
    `candidates` has every candidate's votes so far
    (regional contests at night, the mayors of Bratislava and Košice);
  - `winner`: fully counted, only the winners known
    (municipal contests at night);
  - `final`: definitive, every candidate with votes and flag
    (a council of a by-election of 2019–2022: the elected only,
    [as published](#by-elections-susr-by)).

  A contest missing while the phase is not `none` is not counted yet.
- `counted`: [okrsky processed, okrsky total] of the contest's area,
  null if unknown or not applicable.
- `eligible`, `voters`, `valid`:
  voters on the roll, voters who took part (envelopes issued),
  valid ballots for the contest (for a council: voters with a valid ballot),
  of the counted part; null when unknown.
- `seats`, `filled`: seats elected and seats filled
  (a council can stay partly empty); null if unknown.
  At night a council of several obvody has them per obvod
  only where known beforehand (seats) or all filled.
  A `winner` council without `candidates`
  whose `filled` equals its number of candidates has them all elected
  (a candidate who withdrew but is still listed
  would leave a seat fewer filled):
  the app marks them so (`web/js/live.js` `decodeResults`), without votes.
- `candidates`: `[ballot number, votes, flag]`, sorted by votes.
  The ballot number is the candidacy's (`<contest>#<number>`);
  flag `1` elected, `0` substitute (councils, a party's list),
  `2` on to round 2 (a presidential round 1), `-1` withdrew,
  null otherwise.
  The country-wide contests' records are
  [below](#country-wide-contests).
  - A candidate who withdrew stays on the ballot
    (and in the candidate lists),
    and ŠÚ SR counts their votes among the valid ones and publishes them:
    they are in, never elected.
    The app shows them with a "withdrew" mark
    and leaves them out of calls and of the seats line
    (`decodeResults`, ballots.js `seatPlaces`).
  - ŠÚ SR's council tables per obvod leave such a candidate out
    (`tab08e`, `tab08ex`, and at night `tab06e2`):
    `final` adds them with their votes from the tables per okrsok;
    at night they are missing.
- `areas` (optional): sub-units → `[eligible, voters, valid, {number: votes}]`.
  A sub-unit is a municipality code
  (6 digits, Bratislava and Košice districts included)
  or `obvod:<n>`: a regional council obvod as a whole, at night,
  for the regional president,
  and for a regional council obvod
  while the votes of a municipality in it have not come.
  - At night a regional contest has the municipalities fully counted;
    one whose votes ŠÚ SR has not published yet (`tab06d`, `tab09d`)
    has its turnout alone, `[eligible, voters, null, {}]`,
    which a candidate's map passes over.
  - A final contest of Bratislava or Košice
    lacks the districts whose votes are not known
    (okrsky not told apart, see [Sources](#sources)),
    possibly all of them (`{}`).
    The app gives those districts no figures of their own,
    never their known okrsky summed
    (the map, where none is left, colours the contest's area by its whole,
    as without `areas`).

### Country-wide contests

Read from ŠÚ SR's national tables
([Sources](#national-tables-final)),
in `country.json` and `list/<p>.json`, shaped as above:

- `prezident:SK/n`, a round:
  candidates `[number, votes, flag]`, flag `1` elected,
  `2` on to round 2 (round 1 electing nobody: its two best),
  `-1` withdrew; `areas` per municipality.
- `referendum:SK/q`, a question:
  candidates `[[1, yes, flag], [2, no, flag]]`, `valid` yes + no,
  `seats` 1; flag `1` (and `filled` 1) on the answer that won
  a valid referendum
  (more than half of the eligible took part,
  and it has more than half of the valid votes);
  `areas` per municipality.
- `nrsr:SK`, `ep:SK`, the party contest:
  candidates `[party number, votes, flag]`, flag `1` won seats;
  `seats` the body's, `filled` the seats won,
  `won` `{"<party number>": seats}` of each party that won some;
  `areas` per municipality.
- `nrsr:SK/p`, a party's list (file `list/<p>`):
  candidates `[position, preference votes, flag]`,
  flag `1` elected, `0` substitute of a list that won seats;
  `valid` the party's votes, `seats` its seats, `filled` its elected;
  `areas` per municipality where the package has `tab07e`,
  and okrsky (`okrsky/list/<p>/<kraj>`) where it has `tab07f`,
  each with the party's votes there as `valid`.
  An okrsok's `{position: votes}` has only the persons with votes
  (in NR SR 2023's `tab07f` seven rows in eight are 0);
  one missing has none there.
  A unit has the list where the table has the party's rows of it,
  or where the party has no votes there
  (the wide tables of 2020 have no row there);
  one where the party has votes but the table no rows
  is left out, as not known.
  A list's okrsok files have no `past` (`{}`):
  a list is compared with nothing.
  The app orders a list's persons by the preference rule
  (Act No. 180/2014 Coll. § 68 ods. 5, § 94 ods. 5; NR SR and European
  Parliament alike, the `quota` of `config/elections.toml`, 3 %):
  those whose preference votes reach the quota of the party's votes first,
  by their votes (a tie by list position), then the others by position
  (`results.preference_order`, ballots.js `preferenceRank`).
  Of the whole list that is the official order, the elected first
  as they got their seats, which the check holds a final list to;
  of a unit (`units`, `areas`, an okrsok), the same rule on its votes.
  A list also has its persons' preference votes summed,
  which the app shows beside the party's votes
  (ballots.js `resultsText`), so that it never sums them itself:
  the record's `preferences`, the whole list's,
  and a fifth figure of each of its figures by unit
  (`areas`, `units`, okrsky, the okrsok files' `units`),
  `[eligible, voters, valid, {position: votes}, preferences]`
  (`results.area_json`).

Each of them with `areas`, whatever the phase,
also has `units`, its kraje and okresy,
each its municipalities of `areas` summed
(`results.area_units`):

```json
"units": {
  "kraj": {"1": [512340, 301220, 299870, {"1": 150231, "2": 149639}]},
  "okres": {"101": [33410, 21877, 21790, {"1": 13002, "2": 8788}]}
}
```

- A municipality's kraj and okres are those of the election's
  `candidates.json` (`obce`), as the app's `data/index.json` has them;
  Bratislava and Košice as wholes are in no okres.
- A unit is there where it has a municipality in `areas`;
  the app shows the place's kraj and okres from them
  (live.js `placeResults`)
  and colours the okresy of the map by them (mapmode.js `figures`),
  so that it never sums the municipalities itself.

### A country-wide candidate's polling districts

A president's round and a party's list with okrsky
have `origins` too: for each of its candidates (by number)
who got votes in any of its okrsky,
the okrsky of all its okrsok files (one per kraj)
with the most of their votes and those with the highest share
of the valid ballots
(of the okrsky with at least 30, where two or more have as many),
five each, ties by okrsok, each `[okrsok, votes, valid]`
(`results.origins`):

```json
"origins": {"1": [[["509311/1", 459, 529], …], [["511871/1", 33, 33], …]]}
```

- Only the okrsky where the candidate got votes;
  none for a contest of fewer than two okrsky with valid ballots.
- The candidate card lists them (candidate.js `VoteOrigins`)
  rather than load the contest's okrsok files of every kraj;
  a municipal or regional contest's are in one file, which it ranks alike.
- They add about 1 % to the list files
  (NR SR 2023: 0.51 MB to 46 MB, 0.14 MB gzipped)
  and 0.7 % to a presidential election's `country`.

### A regional president's obvody

A regional president (`predseda:<kraj>`) with `areas`
has `units` too, its regional council obvody by number
(`results.units_of`, `obvod_units`):

```json
"units": {"zsk": {"1": [52110, 18001, 17760, {"1": 9001, "2": 6100}]}}
```

- Final, each obvod is its municipalities of `areas` summed,
  the municipalities of an obvod being those of the `areas`
  of its council contest (`zsk:<kraj>/<n>`) in the same kraj file
  (`results.regional_obvody`): the candidate lists of 2026 do not say
  which obvod a municipality is in (the geometry does), the results do.
  An obvod one of whose municipalities is missing from `areas`
  is left out rather than summed short.
- At night, the obvody counted as wholes (`areas` `obvod:<n>`),
  since the municipalities fully counted are only part of an obvod.
- The app offers the place's obvod as a level of the president's results
  (live.js `placeResults`, scope `zsk`, between the kraj and the
  municipality) and colours the regional obvody of the map by them
  (mapmode.js `figures`), never summing the municipalities itself.

### A city contest's coarsest units

A contest of Bratislava or Košice (`starosta:BA`, `oz:KE/3`)
with `areas` has `units` too:
its districts of `areas` summed by the coarsest units the map colours
(`results.coarse_units`):

```json
"units": {"zsk": {"1": [41433, 15742, 15500, {"1": 9001, "2": 6100}]}}
```

- `zsk`: by the number of the regional obvod each district is in,
  as the regional council contests of the city's kraj file tell
  (`results.file_obvody`);
  where the election has no regional contests
  (a municipal one alone, a by-election), `okres`: by okres.
- Each unit is the districts of `areas` in it summed;
  the map colours the regional obvody, or the okresy, by them
  (mapmode.js `figures`).

### `okrsky/<area>.json`

```json
{
  "contests": {
    "starosta:500011": {"500011/1": [805, 363, 360, {"1": 4, "2": 356}]},
    "zsk:1/1": {"528595/12": [1210, 402, 380, {"5": 101}]}
  },
  "units": {
    "starosta:500011": {"obvod": {"500011/1": [2410, 1102, 1090, {"1": 12, "2": 1078}]}},
    "predseda:4": {"obvod": {"500011/1": [2410, 1102, 1080, {"2": 640}]}}
  },
  "past": {
    "day": "2022-10-29",
    "okrsky": {"501204/1": 2, "500933/1": 0},
    "contests": {
      "starosta:501204": {
        "501204": [8848, 3847, 3766, {"1": 1548}],
        "501204/1": [214, 83, 77, {"1": 23}]
      }
    },
    "totals": {"starosta:501204": [8848, 3847, 3766, {"1": 1548}]},
    "units": {
      "starosta:501204": {"obvod": {"501204/2": [3, [2310, 1003, 981, {"1": 402}]]}}
    }
  }
}
```

Only in the final phase (the night's files have nothing per okrsok).
With the 2026 tables, `units` and `past` the okrsok files take 7.0 MB
(1.9 MB gzipped),
the largest, `okrsky/kraj/7`, 0.78 MB (0.20 MB gzipped).

- `contests`: the contests of the area file beside it,
  each per okrsok → `[eligible, voters, valid, {number: votes}]` as `areas`.
  - An okrsok is `<obec>/<number>`
    in the obec's own numbering of the election;
    the districts of Bratislava and Košice number their own,
    and the cities' own contests (`starosta:BA`, `oz:KE/3`)
    are keyed by those too.
  - Where a contest has every okrsok (as many as `counted[1]`),
    they add up to its `eligible`, `voters`, `valid`
    and candidates' votes
    (not checked for a country-wide contest, whose okrsky are split
    over the kraje's files).
  - A city-wide okrsok that cannot be matched to a single district okrsok
    is left out,
    and so is one whose votes cannot be told apart
    from those of the city's other okrsky of its number
    (see [Sources](#sources)).
- `units`: per contest of `contests` above,
  the units the app narrows its results to that are made of okrsky,
  summed here once (`results.okrsok_units`;
  live.js `placeResults` and the map, mapmode.js `figures`, only read
  them): level → unit → `[eligible, voters, valid, {number: votes}]`
  of the file's okrsky of the contest in it;
  a contest without any is absent (`{}` where none has any).
  - `obvod`: `<obec>/<k>`, a council obvod of an obec split into several
    (of several council contests, or, of a by-election,
    one that elects part of a larger council:
    an obvod above 1, or obvod 1 of a council its term elected in several;
    `addresses.council_parts`, as the app's `councils`),
    its okrsky summed,
    the okrsky of an obvod being those of its council contest
    in the okrsok file of its okres (`results.council_of`);
    for every contest but the councils of that obec.
  - `obec`: of a regional, a city or a country-wide contest
    without `areas`, each obec with okrsky in the file,
    its okrsky summed
    (one with `areas` has the obec's own figures there).
- `past`: the election before the file's contests are compared with
  on this election's okrsky:
  of each contest the newest earlier election that held its kind
  (2022 for 2026; for 2022's municipal contests 2018,
  for its regional ones 2017, the two held apart then;
  a file's contests are all of one half, a kraj's regional,
  an okres's or a city's municipal, so of one election before),
  from the [crosswalk](#the-crosswalk-of-okrsky);
  `{}` where there is nothing to compare
  (the first election of its kind the site has, a by-election,
  which is compared with none, or no figures then).
  - `day`: their election day.
  - `okrsky`: okrsok → how its figures then were found,
    for the okrsky of the obce with several okrsky then or now:
    `0` unknown, `1` same (the same area), `2` identity
    (the same number and registered voters within 10 %),
    `3` approximate (estimated from addresses).
    An okrsok not listed is of an obec with one okrsok then and now:
    the same, its figures the obec's.
  - `contests`: per contest of `contests` above (the 2026 id),
    of its counterpart then (`contests.counterpart`:
    the same contest, a council obvod's body; a party's list has none),
    okrsok or obec → `[eligible, voters, valid, {number: votes}]` then,
    the votes those of the contest's candidates
    who stood for the same office then, under their 2026 ballot numbers
    (from `links/<previous>.json`), whole numbers.
    An obec has an exact record wherever the contest covers all of it
    (a mayor's, a council of one obvod, a regional contest);
    an okrsok one unless its method is `0`.
    A unit one of whose okrsky then has no figures of the contest's body
    (an okrsok left out above) has none: never a sum short of it.
  - `totals`: per contest of `contests` above that is its own counterpart
    (a mayor's, a regional president's, a round, a question,
    a party contest),
    the same contest's own `[eligible, voters, valid, {number: votes}]`
    then, the votes as in `contests`:
    the whole contest, whatever of its units is known.
  - `units`: per contest of `contests` above,
    the election before in the units the app narrows its results to
    that are made of okrsky, summed here once
    (`results.past_units`, live.js `placeResults` and `placePast`
    only read them):
    level → unit → `[method, [eligible, voters, valid, {number: votes}]]`,
    the method the least certain of its parts'
    (`1` same, `2` identity, `3` approximate, from the most certain),
    and only where every part is known,
    as a sum short of some would mislead;
    a unit not known, and a level or contest without any, is absent.
    An okrsok's part is as for the app's `pastOf`:
    its record by its method (none where `0`), or, unlisted in `okrsky`,
    its obec's.
    - `obec`: of a regional, a city or a country-wide contest,
      an obec with okrsky in the file but no record of its own in
      `contests`, its okrsky's summed
      (one with a record is that record, the same area: not repeated).
    - `kraj`, `okres`: of a country-wide contest with `areas`,
      the units of its municipalities there
      (as the area file's [`units`](#country-wide-contests)),
      each its municipalities' then summed
      (an obec's own record, else as `obec`);
      in practice the file's own kraj and its okresy.
    - `zsk`: of a regional president, its regional obvody
      (as the area file's [`units`](#a-regional-presidents-obvody)),
      each its municipalities' then summed as for `kraj`;
      of a city contest, its districts with okrsky in the file
      by regional obvod
      (as the area file's [`units`](#a-city-contests-coarsest-units)),
      or `okres` where the election has none, likewise.
    - `obvod`: `<obec>/<k>`, a council obvod of an obec split into several
      (more than one council contest in `candidates.json`),
      its okrsky's summed,
      the okrsky of an obvod being those of its council contest
      in the okrsok file of its okres (`results.council_of`);
      for every contest but the councils of that obec.
    - `all`: a contest not country-wide without `totals`
      (a council, a regional council obvod), its okrsky's summed.
    - `obce`: such a contest of a kraj or a city
      (a regional council obvod, a city council obvod)
      whose every obec with okrsky in the file has a record of its own
      in `contests`, those summed (method `1`):
      the whole as the map of the election before colours it,
      obec by obec, and as the ballots show it where it is there
      (exact, where `all` may be estimated or missing: live.js `placePast`).
  The app reads them with live.js `pastOf`
  and labels them by method (`pastLabel`, `pastTitle`, strings `past.*`);
  a candidate's map of the election before takes its total
  from `totals`, else from `obce` (a contest of one obec, from its record)
  only where all are known, and its coarsest units
  from `zsk`, `okres` and a regional council obvod's `obce`
  (mapmode.js `gatherPrevious`).

### `turnout.json`

```json
{
  "municipal": {
    "total": [4401237, 1801233],
    "obce": {"500011": [66697, 26953], "500020": [1210, 640]},
    "councils": {"500011/1": [8848, 3847]},
    "zsk": {"4/3": [154120, 60311]}
  },
  "city": {"total": [700311, 280112], "obce": {"BA": [480120, 201311]},
    "zsk": {"1/1": [41433, 15742]}},
  "regional": {"total": [4398210, 1402118]}
}
```

The turnout of the elections of many contests,
which the map colours by turnout (mapmode.js `gatherMunicipal`,
`gatherRegional`), each `[eligible, voters]`
of the records whose two are known, summed here once
(`results.turnout`), so that the app never adds them up:

- `municipal`, of the okres files:
  `obce` each municipality's (Bratislava's and Košice's districts
  included): its mayor's, else its council obvody's summed
  (one electing no mayor, or whose mayor's figures are not known);
  `councils` each council obvod of a municipality split into several
  (`<obec>/<k>`), its own;
  `total` the municipalities' summed;
  `zsk` by regional obvod (`<kraj>/<n>`, as the kraj files' regional
  council contests tell, [above](#a-regional-presidents-obvody)),
  or `okres` where the election has none
  (a municipal one alone, a by-election),
  each its municipalities' summed.
- `city`, of Bratislava's and Košice's files, likewise:
  `obce` each city's, `total` and the coarsest units
  of the districts of its mayor's `areas`.
- `regional`, of the kraj files: `total`, the presidents' summed.

A part without any figure is absent, and the file too
where none has any (a country-wide election).
In 2026 it takes 72 KB (27 KB gzipped).

### The crosswalk of okrsky

`crosswalk.py`, run by the `results` step of the later election,
maps each of its okrsky onto the okrsky of the election before
(of each contest the newest earlier one that held its kind,
[above](#okrskyareajson); a by-election has none),
one crosswalk per election before, of the contests compared with it alone,
with weights, obec by obec, the first that applies:

1. **Whole obec:** an obec with one okrsok now
   takes all of its okrsky then (same).
2. **Addresses:** where both elections place every address of the obec
   in an okrsok (the `addr/` outputs of both),
   the two address registers are paired by IDENTIFIKATOR,
   then by street and house number where unique on each side.
   An okrsok whose addresses lie ≥ 95 % in one okrsok then
   and make up ≥ 95 % of it is the same and takes its exact figures;
   otherwise approximate, its figures then
   the okrsky then weighted by the share of its addresses in each;
   one without a paired address is unknown.
3. **Identity:** the same okrsok numbers
   with registered voters within 10 % of then.
4. Otherwise **unknown**.

A council obvod is counted by how its okrsky were mapped:
whole (of whole obce), or the least certain method of its okrsky;
the area files' contest `past` of an obvod of a council of several
is its okrsky's then summed,
`[method]` with the least certain method,
or `1` (the whole municipality) where one of them is unknown.
The crosswalk is written to `data/build/<day>/crosswalk/<previous>.json`,
one per election before, with its counts; for 2026 → 2022:

| | whole | same | identity | approximate | unknown |
|---|--:|--:|--:|--:|--:|
| okrsky of obce with several okrsky then or now | | 1,997 | 419 | 1,066 | 274 |
| obce, by their least certain okrsok | | 254 | 158 | 173 | 68 |
| council obvody | 2,746 | 287 | 50 | 259 | 40 |

Addresses paired: 807,967 by id, 292 by street, 45,387 unpaired.
An obec still unknown has okrsky changed since 2022
whose rules for one of the elections are not transcribed,
or not drawn, so its addresses cannot be paired.

For 2022 → 2017 (its regional contests alone, the municipal ones
going to 2018): okrsky of obce with several then or now
1,951 same, 182 identity, 742 approximate, 846 unknown;
obce 334, 75, 149, 79; 757,980 addresses paired by id.

### The votes add up

`results.check` is run by `ems check` (on the final and the live results
of `dist/`), by `ems results deploy` and `poll --deploy`,
which deploy no live results that fail it,
and by the `results` step of `ems make`, which writes nothing that fails it,
against the contests and the municipalities of the election's
`candidates.json`:

- `status.json` has the sources of exactly those contests;
- in a single-choice contest that is `final`
  (a mayor, a president, a referendum's question, a party contest),
  in each of its `areas` and in each of its okrsky,
  the candidates' votes are the valid ballots;
- in a council's, no candidate has more votes than the valid ballots,
  nor all together more than `seats` times as many;
- on a party's list, no person has more preference votes
  than the party's votes,
  nor all together more than `preferences` times as many;
  and once final, its elected are the first by the preference rule
  on the whole list's votes, as many as it filled
  (`results.preference_order`, the `quota` of `candidates.json`);
- a party's list's `preferences` and the fifth figure of each of its
  `areas` and okrsky are its persons' votes summed;
- a country-wide contest's `units` are its `areas` summed
  by kraj and okres, a regional president's by regional obvod
  (its council contests' `areas`, or at night its obvody as wholes),
  a city contest's by its coarsest units,
  and no other record has any;
- a country-wide contest's `origins` are what its okrsky of all its
  okrsok files rank (`results.origins`), none without okrsky;
- an okrsok file's `units` are its okrsky summed
  by council obvod (the council contests' okrsky) and obec
  (`results.okrsok_units`);
- an okrsok file's `past` `units` are what its okrsky,
  its records then, the council contests' okrsky
  and the regional council contests' `areas` give
  (`results.past_units`);
- an okrsok file's `past` is of the `day` of the election before
  its contests are compared with, none where there is none
  (`results.Expect.past`, from `cli._compare`);
- `turnout.json` is the area files' turnouts summed
  (`results.turnout`), there exactly where they have any.

A failure names the units.

### Caching

`dist/results/_headers` and `dist/live/_headers`
(from `web/_headers-results` and `web/_headers-live`)
make `<day>/status.json` revalidate on every load
(`Cache-Control: no-cache`),
and let every origin read the files (the app is on the site's own domain).
The other files are kept for a day like the site's other JSON,
under URLs that change with their content (`?v=<hash>`).
A missing file is answered with the part's 404 page, status 404:
where the final results' `status.json` is missing,
the app of an election with `live` reads the live results.

## Sources

### The night (`poll`)

On the night of a municipal and regional election
volbysr.sk publishes JSON files that its own pages read
(`oso/js/functions.js`, `osk/js/functions.js` name them)
and overwrites as records come in.
Cloudflare in front of it rejects Python's default User-Agent,
so `poll` sends a browser-like one naming the project.
It asks conditionally (ETag, Last-Modified),
at most 8 requests at a time over kept connections.

| file | what | used for |
|---|---|---|
| `{oso,osk}/json/tab01.json` | time (SK, EN), units total, processed, … | progress, `source` |
| `{oso,osk}/json/dateSK.json` | time of the last update | `source.time` when tab01 has none |
| `oso/json/tab0dx.json` | Bratislava, Košice: okrsky (C05) | `counted` of their mayors |
| `oso/json/graph01/<obec>.json` | a municipality: % counted (C03), eligible (C04), voters (C05), valid for mayor and council (C09, C10), elected mayor's name, party, votes (C11–C13), seats, filled (C15, C16), type (C17) | municipal `winner` records |
| `oso/json/tab05/<obec>.json` | mayor candidates: number (C01), votes (C05), "zvolený" (C07) | Bratislava, Košice at night; a municipality once it is fully counted |
| `oso/json/tab06e1/<obec>.json`, `tab06e2/…` | council candidates elected, all: number (C01), obvod (C05), votes (C06) | councils once their municipality is fully counted |
| `osk/json/tab02ba.json`, `tab02bb/<kraj>.json`, `tab02bc/<obvod>.json` | turnout per kraj, obvod, municipality, by name: okrsky (C03), processed (C04), eligible (C06), voters (C07), valid president, council (C11, C12) | regional turnout and `counted` |
| `osk/json/tab06b/<kraj>.json`, `tab06c/<obvod>.json`, `tab06d/<obec>.json` | president's candidates per kraj, obvod, municipality (as tab05) | `predseda` records and `areas` |
| `osk/json/tab09c/<obvod>.json`, `tab09d/<obec>.json` | council candidates per obvod, municipality | `zsk` records and `areas` |

Regional obvody are coded kraj + two digits (`105` is `zsk:1/5`);
ŠÚ SR's Bratislava and Košice are `582000` and `599981`.

When each file is fetched:

- **Regional votes of a municipality** (`tab06d`, `tab09d`)
  are fetched once its `tab02bc` row shows all its okrsky counted,
  then not again until the whole regional count is in,
  which fetches every one.
  At 21:00 on the night of 2026
  ŠÚ SR had not published them for the municipalities counted
  (404, simply tried again).
- **A municipality's `tab05` and `tab06e*`**
  are fetched once its `graph01` shows it fully counted,
  until they have come,
  then not again until the whole municipal count is in.
  ŠÚ SR publishes a municipality's `tab05` as soon as it is counted
  (seen on the night of 2026),
  and its record then has every candidate and status `final`.
- **A municipality's `graph01`** is no longer fetched
  once it is fully counted.
- **Second round.**
  Files that become due because others fetched in the same poll
  show their unit fully counted
  are fetched in a second round of that poll, not at the next change.

A mayor elected before the `tab05` has come is known by name only (C11):
the ballot number is that of the contest's candidate
with the same first name and surname
(case, diacritics, titles and word order aside),
the party telling apart two of the same name;
otherwise the contest is left out and logged.

The column meanings are those of the 2026 scripts,
checked against the files of 2018 and 2022 where those tables existed.
If the night proves one wrong, it is a constant at the top of `results.py`,
and the archived raw files can be normalized again.

### Definitive (`final`)

Of a municipal and regional election,
the `results` step of `ems make` reads the CSV zips of both elections,
`https://volbysr.sk/oso/files/OSO<year>_SK_csv.zip`
and `osk/files/OSK<year>_SK_csv.zip`
(the year of the election's day),
the inputs the election's `results` names in `config/elections.toml`
(`ems inputs update` downloads and pins them).

**Tables.**
ŠÚ SR changes the tables between elections,
so the tables and columns read are named per election in `results.py`
(`_FINAL_TABLES`) and checked:
a package lacking one is refused, naming it.
In 2026 they are comma-separated
with headers naming the columns in full
(`Kód obce`, `Počet platných hlasov`, …),
and summed per level:

| Level | Votes | Turnout |
|---|---|---|
| mayors per municipality | `tab05d` | `tab02d` |
| councils per obvod | `tab08e` | `tab02e` |
| Bratislava's and Košice's own contests per city | `tab05x`, `tab08ex` | `tab02x`, `tab02ex` |
| presidents per kraj and municipality | `tab06a`, `tab06c` | `tab02a`, `tab02c` |
| regional councils per obvod and municipality | `tab09b`, `tab09c` | `tab02b`, `tab02c` |

Their flags are `zvolený` (elected),
`náhradník` or, in the regional councils, nothing (substitute),
`X` (withdrew: their votes kept, flag `-1`).
A council obvod's seats are not in the tables, but a whole council's:
where the municipality has several obvody
they come from the candidate lists (`data/build/<election day>/`).

**Okrsok files.**
They come from the tables per okrsok:
the municipal turnout and votes (`tab02f`, `tab05f`, `tab08f`; `Okrsok`)
and the regional (`tab02d`, `tab06d`, `tab09d`; `Volebný okrsok`),
keyed by municipality and okrsok.
`past` comes from the [crosswalk](#the-crosswalk-of-okrsky)
and the final results of the election before.
`final` replaces the contests of the results it has, with their okrsky;
with both elections the phase becomes `final`.

**City okrsky to districts.**
The two cities' own contests are tabulated per city okrsok
(`tab02fx`, `tab05fx`, `tab08fx`), naming no district,
so each okrsok is matched to the district's row of the same okrsok
(`tab02f`) by its voters on the roll and taking part.
Only a pair no other city okrsok and no other district row has is a match,
which gives the okrsok its district's number.
The others (2026: 9 of Bratislava's 388, 5 of Košice's 190)
are left out of the okrsok files, are counted in `final`'s output,
and go to the district most of their council obvod's okrsky are in
for `areas`.

**Okrsky of the same number.**
The cities' vote tables name an okrsok by council obvod and number alone,
but the districts number their own:
a council obvod of several districts has two or three okrsky of a number
(2026: 24 numbers, in Bratislava's obvody 6, 7, 8 and 11
and Košice's 2, 7, 8, 10 and 13),
and each candidate's rows of them come in no fixed order.
Their shares (`Podiel platných hlasov v %`, two decimals)
tell them apart (`city_votes`):

- a mayor's row is a share of its okrsok's valid ballots for mayor,
  which the okrsok's votes add up to;
- a council's is a share of the okrsok's votes together,
  which are at least its valid ballots for the council
  and at most seats times as many,
  no candidate with more votes than those.

Every way of sharing the rows out among the okrsky that fits is found
(up to 100; with more, none is taken).
An okrsok with the same votes in all of them is known;
the others are left out of the okrsok file,
and so is the `areas` entry of each district
to which the ways give different votes, `final` naming them.
In 2026 every mayor's okrsky are known
but two of `starosta:BA`
(obvod 8, number 1, whose two ways differ by a vote of minor candidates);
of the councils, 18 okrsky of `oz:BA/6`, `oz:BA/7`, `oz:BA/8`
and `oz:KE/13` are not,
and those contests have no `areas` for the districts concerned
(`starosta:BA` none for 529419 and 529427).

**Figures as published.**
The figures are ŠÚ SR's as published, never corrected here,
even where they look like a slip in an okrsok's record.
In 2026 `starosta:BA` in Bratislava city obvod 2, okrsok 12
(Podunajské Biskupice, 529311/12)
gives Matúš Vallo (No. 5) 0 votes
and Martin Winkler (No. 6, withdrawn) 268 of 518 (51.73 %),
where Vallo has 54–71 % in every other okrsok numbered 12
and 220–407 votes in every other okrsok of the district,
and Winkler nowhere else more than 14.
The row is unique (no other okrsok shares its obvod and number),
so it is not an artefact of how the city okrsky are resolved;
ŠÚ SR's city total for Winkler (1,031) includes it.

### The regular elections of 2018 and 2017 (`susr`)

Before 2022 the municipal and the regional elections were held apart,
the regional on 4 November 2017, the municipal on 10 November 2018:
each is a regular election of one half (`config.Election.halves`),
with the source `osk` or `oso` only.
`statoffice.read_final` reads ŠÚ SR's XLSX packages of each
into the rows of the 2022 tables and sums them as 2022's:

- 2017 (`OSK_2017_xlsx.zip`): complete, per okrsok;
  `Poznámka` of the votes is 2 elected, 0 withdrawn, 1 neither.
- 2018 (`OSO_2018_xlsx.zip` and the zip of its tables per okrsok,
  `OSO_2018_okrsky-xlsx.zip`): per okrsok, with every council candidate,
  only in the 446 obce and the two cities whose results ŠÚ SR's system
  counted (`IVIS`); elsewhere per obec, the mayors' votes and
  of the councils the elected only, without their obvod's turnout
  where the obec elects in several.
  A council obvod's seats are known where the obec has one obvod,
  or filled every seat (`statoffice.council_seats`).
  The cities' okrsky in a district not counted per okrsok
  are left out of the okrsok files (51 in 2018).

A regular election's halves are each compared (`past`)
with the newest earlier election that held theirs:
2022's municipal contests with 2018's, its regional ones with 2017's.

### By-elections (`susr-by`)

`results.read_by_election` reads ŠÚ SR's package of the municipal
by-elections and new elections of one day
(`OSO<yyyymm>_SK_xlsx.zip`), XLSX tables with the 2026 tables' columns,
as `final` reads those;
only the municipal contests (source `oso`).
A council's seats come from the package where only one obvod of the obec
elects, else from the candidate lists.
Bratislava's and Košice's own contests get no okrsky;
contests of the candidate lists without results are logged.

The packages of 2019–2022 (`OSO_<yyyymm>_xlsx.zip`,
`results.older_by_election`: no `tab0dd`) have less:
the turnout per obec (`tab02bd`, the voters as the envelopes issued),
the mayors' votes per obec (`tab05`)
and of the councils the elected only, with their votes per obvod
(`tab06`), named but not numbered:
each is the candidate of that name in the candidate lists
(`candidates.name_words`: titles, case, diacritics and word order aside),
and fails the step where there is none or several.
A council's record then has the elected alone as its `candidates`;
where the obec elects in several obvody,
its turnout is of none of them, so `counted`, `eligible`, `voters` and
`valid` are null.
No okrsok files.

### National tables (`final`)

`national.read_final` reads the tables of a presidential election
(a package per round, in order), a referendum,
or an election to the NR SR or the European Parliament,
CSV or XLSX, in one zip or as files
(`src/election_map_slovakia/tables.py`), each level from its own table:

| Level | Turnout | Votes | Preference votes (party lists) |
|---|---|---|---|
| whole country | `tab01` | `tab03a` | `tab07a` |
| obec | `tab02d` | `tab03e` | `tab07e` (where the package has it) |
| okrsok | `tab02e` | `tab03f` | `tab07f` (where the package has it) |

Every package the site has gives the preference votes per okrsok
(`tab07f`, `Počet prednostných hlasov pre jednotlivých kandidátov
politických subjektov za okrsky`; `tab_info` of each):
[EP 2019](https://volby.statistics.sk/ep/ep2019/files/EP_2019_SK_xlsx.zip)
(XLSX, a long table over 31 worksheets),
[NR SR 2020](https://volby.statistics.sk/nrsr/nrsr2020/files/NRSR_2020_SK_xlsx.zip)
(XLSX, wide: a worksheet per party, a column per person),
[NR SR 2023](https://volby.statistics.sk/nrsr/nrsr2023/files/NRSR2023_SK_csv.zip)
and [EP 2024](https://volby.statistics.sk/ep/ep2024/files/EP2024_SK_csv.zip)
(CSV, long).
In each, every okrsok of `tab03f` has the lists of its parties
(none left out),
and a list's okrsky add up to its municipalities of `tab07e`.
The lists' okrsok files, with their preference votes summed, take
6.2 MB (EP 2024) to 14.3 MB (NR SR 2023) per election, the largest file
0.32 MB.

- A party's seats are those of `tab03a` (`Počet získaných mandátov`),
  else of `tab04` (`Pridelené mandáty spolu`);
  its elected those whose place after the preference votes
  (`tab07a`, `Poradie po zohľadnení prednostného hlasovania`)
  is within its seats, else those of `tab06`.
- A round's notes (`zvolený`, `X`, a note starting `postup`) give the flags;
  where round 1 marks nobody,
  its two best who did not withdraw go on (flag 2);
  round 2 without a note elects the best.
- A referendum's yes and no (`Počet hlasov "ÁNO"`, `Počet hlasov "NIE"`)
  are per question where a table has `Číslo otázky`, else of question 1.
- Where the okrsok table has no kraj code,
  the kraj comes from the obec.
- ŠÚ SR words a column differently from one election and table to the next:
  each is named by its aliases in `national.py`,
  and one missing fails naming the table,
  the columns wanted and the columns found
  (an old CSV of coded headers, `OBEC|OKRSOK|P_ANO`, is not read:
  take its XLSX tables).
