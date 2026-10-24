# Live results

On election night (24–25 October 2026) the app shows the results as they are
counted. They come from a second Cloudflare Pages project,
`election-map-slovakia-live` (`live_pages_project` in `config/site.toml`),
served at `https://live.volebnamapa.sk` (`live_url`), which holds only the
results JSON and is deployed by hand from a local machine. The main site
stays as released; its app reads `<live_url>/status.json` and the area files
it names (`web/js/live.js`). `ems results` makes, serves and deploys that
site; the code is `src/election_map_slovakia/results.py`.

```sh
uv run ems results poll                 # every 60 s: volbysr.sk → live/
uv run ems results poll --deploy        # … and deploy after every change
uv run ems results poll --once          # one poll, e.g. to try it
uv run ems results final OSO2026_SK_csv.zip OSK2026_SK_csv.zip
uv run ems results fake mid             # dummy results: none, early, mid, late, final
uv run ems results serve                # live/ at http://127.0.0.1:8766/
uv run ems results deploy               # live/ → Cloudflare Pages, asks first
```

Every command takes `--dir` for another directory than `live/` (git-ignored).
`poll`, `fake` and `final` read `data/build/` (`ems make` first).

## Testing the app with dummy results

```sh
uv run ems results fake mid             # or none, early, late, final; --seed N
uv run ems results serve &
EMS_LIVE_URL=http://127.0.0.1:8766 uv run ems make
uv run ems serve
```

Driving it in a headless browser is in [testing.md](testing.md). A build
with `EMS_LIVE_URL` reads the results at any time; the released site reads
them only from the polls' closing for `live_days` days, then once per page
load (docs/deploy.md, "Live results").

`fake` writes plausible results of the counting at a stage: `none` (polls
closed, nothing counted), `early` (regional ~10 % counted, no municipal),
`mid` (regional ~60 %, ~40 % of the municipalities with their winners, the
Bratislava and Košice mayors ~50 %), `late` (everything counted, municipal
winners only, regional and city mayors still partial), `final` (definitive:
all candidates, flags, `areas` per municipality); at night the regional
contests have `areas` for the municipalities counted, the president's also
per obvod. Turnout follows each
area's last election, votes a stable random distribution; the counted parts
only grow from stage to stage (same seed). The first kraj's president race
stays too close to call to the end; the regional obvod with the fewest
voters is fully counted by `mid` with a landslide that decides it under the
app's rule (the uncounted voters are at most `max(ceil(1.1 × eligible in
2022), counted eligible) − counted eligible`; a candidate is sure of a seat
when fewer than `seats` others could still reach their votes).

## Setup, once

1. Log in to Wrangler: `npx wrangler login`, or set `CLOUDFLARE_API_TOKEN`
   (permission "Cloudflare Pages: Edit") and `CLOUDFLARE_ACCOUNT_ID`.
2. Create the Pages project:
   `npx wrangler pages project create election-map-slovakia-live --production-branch=main`.
3. Give it its first content: `uv run ems results poll --once`, then
   `uv run ems results deploy`.
4. Add the custom domain: in the Cloudflare dashboard, Workers & Pages →
   election-map-slovakia-live → Custom domains → Set up a custom domain →
   `live.volebnamapa.sk` → Activate. With the volebnamapa.sk zone in the
   same account, the `live` DNS record is created automatically. Wait for
   the domain to show Active (the certificate takes a few minutes).
5. Make sure no Cache Rule or Page Rule of the zone matches
   `live.volebnamapa.sk` with "Cache Everything" or a fixed edge lifetime:
   it would keep serving old results. If a wildcard rule does, add a
   bypass for `live.volebnamapa.sk/*`.
6. Check: `curl -sI https://live.volebnamapa.sk/status.json` answers 200
   with `access-control-allow-origin: *` and `cache-control: no-cache`.

## Testing against a real deployment

Fake results must never reach `live.volebnamapa.sk` once a released main
site reads it. Deploy them to a preview branch instead, which Pages serves
at an address of its own, and point a local build of the site at it:

```sh
uv run ems results fake mid
npx wrangler pages deploy live --project-name=election-map-slovakia-live --branch=test
EMS_LIVE_URL=https://test.election-map-slovakia-live.pages.dev uv run ems build
uv run ems serve                        # http://127.0.0.1:8765/
uv run ems results poll --once          # live/ back to the real state
```

This tries what the local `serve` cannot: the live site's headers on
Cloudflare (CORS, `no-cache`) and the main site's CSP with a real origin.

## Election night

1. Before 20:00: `uv run ems results poll --once`; it should end with
   phase `none`, and `live/` has `status.json`. `uv run ems results deploy`
   once, so that the live site answers.
2. The first real files: the meanings of the night files' columns are
   inferred from the 2026 site's scripts and the samples of earlier
   elections (constants at the top of `results.py`), as no 2026 file
   existed to look at. So start with `uv run ems results poll`, without
   deploying. When the first regional figures appear (about 21:00 in
   2022), compare a few contests in `live/` with volbysr.sk, then
   `uv run ems results deploy`.
3. Once they match: `uv run ems results poll --deploy`. It fetches the
   progress files every interval and the rest only when they changed,
   rewrites `live/` only when its content changed and deploys after each
   change. Keep the machine awake and online. Every file it fetched is
   kept under `data/raw/results/<UTC time>/`, so a problem found later can
   be replayed. It logs what it skipped: files still missing (404),
   unexpected data, a municipality's elected mayor whose name fits no
   single candidate. If something goes wrong, stop it: the last deployment
   stays up.
4. The night ends in the timestamps' clock change (03:00 CEST becomes
   02:00 CET); `poll` keeps ŠÚ SR's times with their offset.
5. The definitive results: in 2022 they were published the next day around
   noon, when the site switched to "Definitívne výsledky"; `poll` makes the
   municipal contests final once every municipality is counted. The CSV
   packages came a week later (expected
   `https://volbysr.sk/oso/files/OSO2026_SK_csv.zip` and
   `https://volbysr.sk/osk/files/OSK2026_SK_csv.zip`): then stop `poll` and
   run `uv run ems results final OSO2026_SK_csv.zip OSK2026_SK_csv.zip` and
   `uv run ems results deploy`.

`deploy` shows what `live/` holds (phase, version, counts), checks it
against the format below, and runs
`npx --yes wrangler pages deploy live --project-name=election-map-slovakia-live --branch=main`
after asking (`--yes`: without).

## Files

All JSON, UTF-8, compact. An area file has the same name as the main site's
area file of its contests, without `data/`: `okres/<okres>`, `city/BA`,
`city/KE`, `kraj/<1-8>`.

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
  "files": {"kraj/1": "a1b2c3d4", "okres/101": "…"}
}
```

- `phase`: `none` (nothing counted yet), `partial` (election night),
  `final` (definitive results of both elections).
- `version` changes whenever phase, sources or any file does; a run that
  changes nothing writes nothing. `files` maps every area file to the first
  8 hex digits of the SHA-256 of its content; the app fetches
  `<live>/<area>.json?v=<hash>`.
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
  under 100 % until every unit is in, and by `counted` where they are null.

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
  them per obvod only where known beforehand (seats) or all filled.
- `candidates`: `[ballot number, votes, flag]`, sorted by votes; the ballot
  number is the candidacy's (`<contest>#<number>`), flag `1` elected, `0`
  substitute (councils), null otherwise. Withdrawn candidates are left out.
- `areas` (optional): sub-units, a municipality code (6 digits, Bratislava
  and Košice districts included) or `obvod:<n>` (a regional council obvod,
  for the regional president at night, beside the municipalities fully
  counted) → `[eligible, voters, valid, {number: votes}]`.

### `_headers`, `404.html`

`_headers` answers every file with `Access-Control-Allow-Origin: *` (public
read-only data, read by the main site's origin), `Cache-Control: no-cache`
(revalidated on every request) and `X-Content-Type-Options: nosniff`.
`404.html` makes Pages answer a missing file with status 404; without one it
would answer with an index page and 200.

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
| `oso/json/tab05/<obec>.json` | mayor candidates: number (C01), votes (C05), "zvolený" (C07) | Bratislava, Košice at night; every municipality once all are counted |
| `oso/json/tab06e1/<obec>.json`, `tab06e2/…` | council candidates elected, all: number (C01), obvod (C05), votes (C06) | councils once all are counted |
| `osk/json/tab02ba.json`, `tab02bb/<kraj>.json`, `tab02bc/<obvod>.json` | turnout per kraj, obvod, municipality, by name: okrsky (C03), processed (C04), eligible (C06), voters (C07), valid president, council (C11, C12) | regional turnout and `counted` |
| `osk/json/tab06b/<kraj>.json`, `tab06c/<obvod>.json`, `tab06d/<obec>.json` | president's candidates per kraj, obvod, municipality (as tab05) | `predseda` records and `areas` |
| `osk/json/tab09c/<obvod>.json`, `tab09d/<obec>.json` | council candidates per obvod, municipality | `zsk` records and `areas` |

Regional obvody are coded kraj + two digits (`105` is `zsk:1/5`);
ŠÚ SR's Bratislava and Košice are `582000` and `599981`. A municipality's
regional votes (`tab06d`, `tab09d`) are fetched once its `tab02bc` row
shows all its okrsky counted, then not again until the whole regional count
is in, which fetches every one; whether ŠÚ SR publishes them before that is
not known (a 404 is simply tried again). `tab05` and `tab06e*` of every
municipality are fetched only once the municipal election is fully
counted; a municipality's `graph01` no longer once it is. The night's
municipal winners
come by name only (C11): the ballot number is that of the contest's
candidate with the same first name and surname (case, diacritics, titles
and word order aside), the party telling apart two of the same name;
otherwise the contest is left out and logged. The column meanings are those
of the 2026 scripts, checked against the files of 2018 and 2022 where those
tables existed; if the night proves one wrong, it is a constant at the top
of `results.py`, and the archived raw files can be normalized again.

**Definitive (`final`).** The CSV zips of 2026 are expected in the layout of
2022 (`data/fallback/results-oso2022/`, `results-osk2022/`): `|`-separated
tables per okrsok, named in the zip's `tab_info` table. The tables are
chosen by their titles there, not by the letters ending their names, and
checked for the columns used: units (`P_ALL_OKRSOK`), turnout (`P_ZAP`,
`P_ZUC`, valid ballots per contest), seats (`P_POS_VOL`, `P_POS_ZVOL`) and
the votes of mayors, councils and presidents (`PC_HL`, `P_HL`, `KANDIDAT`:
1 elected, 0 substitute, X withdrawn). Votes and turnout are summed per
contest; `areas` are per municipality for the regional contests and, for
those of Bratislava and Košice, per city district: the city's tables name
no district, so each okrsok is matched to the district's row of the same
okrsok by its voters on the roll and taking part. `final` replaces the
contests of `live/` it has; with both elections the phase becomes `final`.
