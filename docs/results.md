# Results

The app shows the results of the elections: on election night (24–25
October 2026) as they are counted, then the definitive ones. They are part
of the site, one directory per election, keyed by its day:
`data/build/results/<election day>/` (written by `ems results` and by the
`results` step of `ems make`), which `ems build` copies to
`dist/results/<election day>/`. The app reads `status.json` there and the
files it names from the site's own origin (`web/js/live.js`; the path is
`results` in the app shells' config). A later election gets a directory of
its own and leaves this one as it is. The code is
`src/election_map_slovakia/results.py`.

```sh
uv run ems results poll                 # every 60 s: volbysr.sk → the results
uv run ems results poll --deploy        # … and build and deploy the site after every change
uv run ems results poll --once          # one poll, e.g. to try it
uv run ems results final                # the definitive CSV zips → the results
uv run ems results fake mid             # dummy results: none, early, mid, late, final
uv run ems results deploy               # build the site, upload it to Cloudflare Pages, asks first
```

`poll`, `final` and `fake` write the election's results directory, or the
directory given with `--dir`, and read `data/build/` (`ems make` first).
`ems serve` serves the results with the rest of the site.

## Final results as inputs

Once published, the definitive packages are pinned in `config/inputs.toml`
like every other input, as `results-oso<year>` and `results-osk<year>`, the
year of the election day (`election` in `site.toml`), with committed
copies in `data/fallback/`. The `results` step of `ems make` writes the
election's results from them, in place of what the directory held, as of
the packages' newest data (`updated`, `version`), so that a release's
results are, like every other file of the site, a pure function of its
inputs and the same on every machine. Without them configured the step
leaves the directory as `ems results` left it (absent: no results). For
2026 both are pinned: the site shows the definitive results.

`ems results final` reads the same inputs where they are configured; zips
or directories given are read instead, and without either it downloads the
packages (the morning after a future election, before they are pinned).
It replaces the contests of the results it has. A `poll`, `final` or `fake`
that changes the election's results directory makes the next `ems make`
run the `results` step again, so a release never keeps dummy or night
results over the pinned final ones.

## Testing the app with dummy results

```sh
uv run ems results fake mid             # or none, early, late, final; --seed N
EMS_RESULTS_ANYTIME=1 uv run ems build
uv run ems serve
```

Driving it in a headless browser is in [testing.md](testing.md). A build
with `EMS_RESULTS_ANYTIME=1` reads the results every minute at any time;
otherwise the app polls them only with `live` on (site.toml), from the
polls' closing for `live_days` days, and reads them once per page load
else (docs/deploy.md, "Results"). `fake` replaces the
election's results; with the 2026 inputs pinned, the next `ems make`
puts the final results back (`--dir` writes elsewhere, where the site
does not look).

`fake` writes plausible results of the counting at a stage: `none` (polls
closed, nothing counted), `early` (regional ~10 % counted, no municipal),
`mid` (regional ~60 %, ~40 % of the municipalities with their winners, the
Bratislava and Košice mayors ~50 %), `late` (everything counted, municipal
winners only, regional and city mayors still partial), `final` (definitive:
all candidates, flags, `areas` per municipality, and the okrsok files); at
night the regional contests have `areas` for the municipalities counted,
the president's also per obvod. Turnout follows each
area's last election, votes a stable random distribution; the counted parts
only grow from stage to stage (same seed). The first kraj's president race
stays too close to call to the end; the regional obvod with the fewest
voters is fully counted by `mid` with a landslide that decides it under the
app's rule (the uncounted voters are at most `max(ceil(1.1 × eligible in
2022), counted eligible) − counted eligible`; a candidate is sure of a seat
when fewer than `seats` others could still reach their votes). The okrsky
of `final`: as many per municipality as the 2026 list of okrsky
(`units-oso2026`) has, a council obvod's those of its rule set where it
gives them (none for an obvod of a council of several whose rule set does
not; a council of one obvod has all of the municipality's), the figures
split at random so that they add up to the contest's and keep to the check
below (a mayor's or president's votes are each unit's valid ballots); most
municipalities of several okrsky have a made-up `past`. `fake` reads that
list from `data/raw/` (`ems fetch`).

Fake results must never reach the deployed site. To try them on
Cloudflare, deploy a build to a preview branch, which Pages serves at an
address of its own:

```sh
uv run ems results fake mid
EMS_RESULTS_ANYTIME=1 uv run ems build
npx wrangler pages deploy dist --project-name=election-map-slovakia --branch=test
uv run ems make                         # the results back to those of the inputs
```

## A future election night

The results are deployed with the site: each change is a production
deployment of the main Pages project (`pages_project`), built locally, as
a release (a version tag) makes one through CI. Set up Wrangler once: `npx
wrangler login`, or `CLOUDFLARE_API_TOKEN` (permission "Cloudflare Pages:
Edit") and `CLOUDFLARE_ACCOUNT_ID`.

1. Before the polls close: `uv run ems results poll --once`; it should end
   with phase `none`, and the election's results directory has
   `status.json`. `uv run ems results deploy` once, so that the site
   answers `results/<day>/status.json`.
2. The first real files: the meanings of the night files' columns are
   inferred from the 2026 site's scripts and the samples of earlier
   elections (constants at the top of `results.py`). So start with
   `uv run ems results poll`, without deploying. When the first regional
   figures appear (about 21:00 in 2022), compare a few contests of the
   results directory with volbysr.sk, then `uv run ems results deploy`.
3. Once they match: `uv run ems results poll --deploy`. It fetches the
   progress files every interval and the rest only when they changed,
   rewrites the results only when their content changed and then builds
   the site (`ems build`, without the slower steps of `make`) and deploys
   it. Keep the machine awake and online. Every file it fetched is kept
   under `data/raw/results/<UTC time>/`, so a problem found later can be
   replayed. It logs what it skipped: files still missing (404),
   unexpected data, a municipality's elected mayor whose name fits no
   single candidate. If something goes wrong, stop it: the last deployment
   stays up.
4. The night ends in the timestamps' clock change (03:00 CEST becomes
   02:00 CET); `poll` keeps ŠÚ SR's times with their offset.
5. The definitive results: in 2022 they were published the next day around
   noon, when the site switched to "Definitívne výsledky"; `poll` makes the
   municipal contests final once every municipality is counted. In 2026 the
   CSV packages came with them, the regional at 04:09 and the municipal at
   12:04 on 25 October (in 2022 a week later): then stop `poll` and run
   `uv run ems results final` and `uv run ems results deploy`.
6. Then pin the packages: add `results-oso<year>` and `results-osk<year>`
   to `config/inputs.toml` with their sha256 and copies in
   `data/fallback/` (as for 2026), `uv run ems fetch`, `uv run ems make`,
   and release: from then on every release carries the final results.

`deploy` shows what the results hold (phase, version, counts), checks them
against the format below, runs `ems build` and then
`npx --yes wrangler pages deploy dist --project-name=election-map-slovakia --branch=main`
after asking (`--yes`: without). It does not run `ems check`, which takes
longer; a release does.

## Files

All JSON, UTF-8, compact. An area file has the same name as the main site's
area file of its contests, without `data/`: `okres/<okres>`, `city/BA`,
`city/KE`, `kraj/<1-8>`. With the final results each has an okrsok file
beside it, `okrsky/<area>` (`okrsky/okres/101`, `okrsky/city/BA`,
`okrsky/kraj/1`).

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

- `phase`: `none` (nothing counted yet), `partial` (election night),
  `final` (definitive results of both elections).
- `version` changes whenever phase, sources or any file does; a run that
  changes nothing writes nothing. `files` maps every area and okrsok file
  to the first 8 hex digits of the SHA-256 of its content; the app fetches
  `/results/<day>/<file>.json?v=<hash>`.
- `source.*.time`: ŠÚ SR's time of the data, ISO 8601 with its offset (ŠÚ
  SR writes SELČ/CEST or SEČ/CET after the time; the clocks go back at
  03:00 on 25 October). `counted`: [units processed, units total], null
  when unknown. `voters`: [registered voters of the units counted, of all
  units], null when unknown (`poll` and `fake`; the final results are
  complete): a unit (a kraj's president; a municipality's mayor, or else
  its council, Bratislava's and Košice's districts rather than the cities)
  counts whole once it is in, however many voted there; one partly counted
  with the registered voters of its okrsky counted, of as many as at its
  last election or as counted, if more; one not counted yet with those of
  its last election. The app shows how far the count has got by these,
  under 100 % until every unit is in, and by `counted` where they are null;
  in tenths below 10 % and never as 0 % once anything is counted, as the
  small municipalities, counted first, are a fraction of a per cent of the
  voters.

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

- `status`: `partial` — counting in progress, `candidates` has every
  candidate's votes so far (regional contests at night, the mayors of
  Bratislava and Košice); `winner` — fully counted, only the winners known
  (municipal contests at night); `final` — definitive, every candidate with
  votes and flag. A contest missing while the phase is not `none` is not
  counted yet.
- `counted`: [okrsky processed, okrsky total] of the contest's area, null if
  unknown or not applicable.
- `eligible`, `voters`, `valid`: voters on the roll, voters who took part
  (envelopes issued), valid ballots for the contest (for a council: voters
  with a valid ballot), of the counted part; null when unknown.
- `seats`, `filled`: seats elected and seats filled (a council can stay
  partly empty); null if unknown. At night a council of several obvody has
  them per obvod only where known beforehand (seats) or all filled. A
  `winner` council without `candidates` whose `filled` equals its number
  of candidates has them all elected (a candidate who withdrew but is
  still listed would leave a seat fewer filled): the app marks them so
  (`web/js/live.js` `decodeResults`), without votes.
- `candidates`: `[ballot number, votes, flag]`, sorted by votes; the ballot
  number is the candidacy's (`<contest>#<number>`), flag `1` elected, `0`
  substitute (councils), `-1` withdrew, null otherwise. A candidate who
  withdrew stays on the ballot (and in the candidate lists), and ŠÚ SR
  counts their votes among the valid ones and publishes them: they are in,
  never elected; the app shows them with a "withdrew" mark and leaves them
  out of calls and of the seats line (`decodeResults`, ballots.js
  `seatPlaces`). ŠÚ SR's council tables per obvod leave such a candidate
  out (`tab08e`, `tab08ex`, and at night `tab06e2`): `final` adds them
  with their votes from the tables per okrsok; at night they are missing.
- `areas` (optional): sub-units, a municipality code (6 digits, Bratislava
  and Košice districts included) or `obvod:<n>` (a regional council obvod
  as a whole, at night: for the regional president, and for a regional
  council obvod while the votes of a municipality in it have not come)
  → `[eligible, voters, valid, {number: votes}]`. At night a regional
  contest has the municipalities fully counted; one whose votes ŠÚ SR has
  not published yet (`tab06d`, `tab09d`) has its turnout alone,
  `[eligible, voters, null, {}]`, which a candidate's map passes over. A
  final contest of Bratislava or Košice lacks the districts whose votes are
  not known (okrsky not told apart, "Sources"), possibly all of them
  (`{}`): the app gives those districts no figures of their own, never
  their known okrsky summed (the map, where none is left, colours the
  contest's area by its whole, as without `areas`).

The votes add up (`results.check`, run by `ems check`, `ems results
deploy`, and by `final` and the `results` step of `ems make`, which write
nothing that fails it): in a contest of a mayor or president that is
`final`, in each of its `areas` and in each of its okrsky, the candidates'
votes are the valid ballots; in a council's no candidate has more votes
than the valid ballots, nor all together more than `seats` times as many.
A failure names the units.

### `okrsky/<area>.json`

```json
{
  "contests": {
    "starosta:500011": {"500011/1": [805, 363, 360, {"1": 4, "2": 356}]},
    "zsk:1/1": {"528595/12": [1210, 402, 380, {"5": 101}]}
  },
  "past": {"500011/1": [805, 363]}
}
```

Only in the final phase (the night's files have nothing per okrsok).

- `contests`: the contests of the area file beside it, each per okrsok →
  `[eligible, voters, valid, {number: votes}]` as `areas`. An okrsok is
  `<obec>/<number>` in the obec's own numbering of the election; the
  districts of Bratislava and Košice number their own, and the cities'
  own contests (`starosta:BA`, `oz:KE/3`) are keyed by those too. Where a
  contest has every okrsok (as many as `counted[1]`), they add up to its
  `eligible`, `voters`, `valid` and candidates' votes; a city-wide okrsok
  that cannot be matched to a single district okrsok is left out, and so
  is one whose votes cannot be told apart from those of the city's other
  okrsky of its number ("Sources").
- `past`: `[eligible, voters]` of the okrsok in the regular municipal
  election of 2022, for the okrsky of the contests above, only where the
  obec has the same okrsok numbers as in 2022 and each okrsok's registered
  voters are within 10 % of 2022's; absent elsewhere. `{}` when none, and
  always in the regional files (`okrsky/kraj/*`): a municipal turnout, it
  goes with the municipal contests (`okrsky/okres/*`, `okrsky/city/*`).

With the 2026 tables the okrsok files take 3.8 MB (1.0 MB gzipped), the
largest, `okrsky/kraj/7`, 0.48 MB (0.12 MB gzipped).

### Caching

`dist/_headers` (from `web/_headers`) makes `results/<day>/status.json`
revalidate on every load (`Cache-Control: no-cache`); the other files are
kept for a day like the site's other JSON, under URLs that change with
their content (`?v=<hash>`). A missing file is answered with the site's
404 page, status 404.

## Sources

**The night (`poll`).** volbysr.sk publishes JSON files that its own pages
read (`oso/js/functions.js`, `osk/js/functions.js` name them) and overwrites
as records come in; Cloudflare in front of it rejects Python's default
User-Agent, so `poll` sends a browser-like one naming the project. It asks
conditionally (ETag, Last-Modified), at most 8 requests at a time over kept
connections.

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
ŠÚ SR's Bratislava and Košice are `582000` and `599981`. A municipality's
regional votes (`tab06d`, `tab09d`) are fetched once its `tab02bc` row
shows all its okrsky counted, then not again until the whole regional count
is in, which fetches every one; at 21:00 on the night of 2026 ŠÚ SR had
not published them for the municipalities counted (404, simply tried
again). A municipality's `tab05` and `tab06e*` are fetched once its
`graph01` shows it fully counted, until they have come, then not again
until the whole municipal count is in: ŠÚ SR
publishes a municipality's `tab05` as soon as it is counted (seen on the
night of 2026), and its record then has every candidate and status
`final`. A municipality's `graph01` is no longer fetched once it is fully
counted. Files that become due because others fetched in the same poll
show their unit fully counted are fetched in a second round of that poll,
not at the next change. A mayor elected before the `tab05` has come is
known by name only (C11): the ballot number is that of the contest's
candidate with the same first name and surname (case, diacritics, titles
and word order aside), the party telling apart two of the same name;
otherwise the contest is left out and logged. The column meanings are those
of the 2026 scripts, checked against the files of 2018 and 2022 where those
tables existed; if the night proves one wrong, it is a constant at the top
of `results.py`, and the archived raw files can be normalized again.

**Definitive (`final`).** `final` reads the CSV zips of both elections,
`https://volbysr.sk/oso/files/OSO<year>_SK_csv.zip` and
`osk/files/OSK<year>_SK_csv.zip` (the year of `election` in `site.toml`):
the inputs `results-oso<year>` and `results-osk<year>` where
`config/inputs.toml` has them, else downloaded and kept like the night's
files under `data/raw/results/<UTC time>/`; zips or directories given are
read instead.
ŠÚ SR changes the tables between elections, so the tables and columns read
are named per election in `results.py` (`_FINAL_TABLES`) and checked: a
package lacking one is refused, naming it. In 2026 they are comma-separated
with headers naming the columns in full (`Kód obce`, `Počet platných
hlasov`, …), and summed per level: the mayors per municipality (`tab05d`,
turnout `tab02d`), the councils per obvod (`tab08e`, `tab02e`), Bratislava's
and Košice's own contests per city (`tab05x`, `tab08ex`, `tab02x`,
`tab02ex`), the presidents per kraj and municipality (`tab06a`, `tab06c`,
`tab02a`, `tab02c`) and the regional councils per obvod and municipality
(`tab09b`, `tab09c`, `tab02b`, `tab02c`). Their flags are `zvolený`
(elected), `náhradník` or, in the regional councils, nothing (substitute),
`X` (withdrew: their votes kept, flag `-1`). A council obvod's seats are
not in the tables, but a whole council's: where the municipality has
several obvody they come from the candidate lists (`data/build/`). The
okrsok files come from the tables per okrsok: the municipal turnout and
votes (`tab02f`, `tab05f`,
`tab08f`; `Okrsok`) and the regional (`tab02d`, `tab06d`, `tab09d`;
`Volebný okrsok`), keyed by municipality and okrsok. The two cities' own
contests are tabulated per city okrsok (`tab02fx`, `tab05fx`, `tab08fx`),
naming no district, so each okrsok is matched to the district's row of the
same okrsok (`tab02f`) by its voters on the roll and taking part. Only a
pair no other city okrsok and no other district row has is a match, which
gives the okrsok its district's number; the others (2026: 9 of
Bratislava's 388, 5 of Košice's 190) are left out of the okrsok files, are
counted in `final`'s output, and go to the district most of their council
obvod's okrsky are in for `areas`.

The cities' vote tables name an okrsok by council obvod and number alone,
but the districts number their own: a council obvod of several districts
has two or three okrsky of a number (2026: 24 numbers, in Bratislava's
obvody 6, 7, 8 and 11 and Košice's 2, 7, 8, 10 and 13), and each
candidate's rows of them come in no fixed order. Their shares (`Podiel
platných hlasov v %`, two decimals) tell them apart (`city_votes`): a
mayor's row is a share of its okrsok's valid ballots for mayor, which the
okrsok's votes add up to; a council's a share of the okrsok's votes
together, which are at least its valid ballots for the council and at most
seats times as many, no candidate with more votes than those. Every way of
sharing the rows out among the okrsky that fits is found (up to 100; with
more, none is taken): an okrsok with the same votes in all of them is
known; the others are left out of the okrsok file, and so is the `areas`
entry of each district to which the ways give different votes, `final`
naming them. In 2026 every mayor's okrsky but two of `starosta:BA` (obvod
8, number 1, whose two ways differ by a vote of minor candidates) are
known; of the councils, 18 okrsky of `oz:BA/6`, `oz:BA/7`, `oz:BA/8` and
`oz:KE/13` are not, and those contests have no `areas` for the districts
concerned (`starosta:BA` none for 529419 and 529427).

The figures are ŠÚ SR's as published, never corrected here, even where
they look like a slip in an okrsok's record: in 2026 `starosta:BA` in
Bratislava city obvod 2, okrsok 12 (Podunajské Biskupice, 529311/12)
gives Matúš Vallo (No. 5) 0 votes and Martin Winkler (No. 6, withdrawn)
268 of 518 (51.73 %), where Vallo has 54–71 % in every other okrsok
numbered 12 and 220–407 votes in every other okrsok of the district, and
Winkler nowhere else more than 14. The row is unique (no other okrsok
shares its obvod and number), so it is not an artefact of how the city
okrsky are resolved; ŠÚ SR's city total for Winkler (1,031) includes it.

`past` per okrsok comes from `okrsky_2022` of `data/build/candidates.json`;
`final` reports how many obce matched (2026: 417 of the 630 with several
okrsky in 2022). `final` replaces the contests of the results it has, with
their okrsky; with both elections the phase becomes `final`.
