# The pipeline

The site is built by a Python pipeline that turns official open data into
the static files in `dist/`. Its command is `ems` (**E**lection **M**ap
**S**lovakia):

```sh
uv run ems fetch                     # download every input
uv run ems fetch --only addresses    # just the named inputs
uv run ems fetch --force             # ignore server validators
uv run ems candidates                # data/build/candidates.json
uv run ems addresses                 # data/build/addr/, data/build/obvod-addresses/
uv run ems geo                       # data/build/geo/
uv run ems geo --preview 806         # plus SVG previews in data/build/preview/
uv run ems build                     # dist/
uv run ems check                     # verify dist/ before deploying
uv run ems make                      # candidates, addresses, geo, build, check
uv run ems make --force              # also redo the steps that are up to date
uv run ems serve --port 8000         # http://127.0.0.1:8000/
uv run ems results poll --deploy     # election night: volbysr.sk → live/ → Pages
uv run ems results fake mid          # dummy live results for testing the app
```

To rebuild the site after `fetch` (or after changing `config/`,
`data/curated/` or `web/`), run `uv run ems make` and then `uv run ems serve`.
`make` runs `candidates`, `addresses`, `geo`, `build` and `check` in this
order, each as if run on its own, and stops at the first that fails, naming
it and the steps it did not run.

`candidates`, `geo` and `addresses` skip their work when nothing they depend
on has changed since they last succeeded: they record the sha256 of their
input files (downloads, `data/curated/obvody/`, `data/build/candidates.json`),
the configuration they use (`config/inputs.toml` entries, overrides) and their
code (their modules and the package modules these import, the CLI, and the
Python, NumPy, Shapely/GEOS and pyproj/PROJ versions) in
`data/build/<step>.stamp.json`, and run again when any of it differs, when
an output is missing, or with `--force`. They say which it was, or that they
are up to date. A comment added to a TOML file reruns the steps that read the
file as text (curated obvody) but not those that read its values
(overrides). `geo --preview` always runs. `build` and `check` always run (4
and 6 s); an up-to-date `make` takes about 10 s instead of 40.

Every command but `serve` reports on stderr what it is doing as it starts
each part, with a running count or percentage for the long ones (downloads,
the address register, writing and measuring files), and how long each part
took; on a terminal a part's count updates in place. The summaries described
below go to stdout, so `uv run ems geo > geo.txt` keeps just the summary.

`fetch` downloads the files declared in `config/inputs.toml` (the official
election and boundary files, and Natural Earth's countries) into
`data/raw/<name>/` and records URL, sha256, size and retrieval time in
`data/raw/manifest.json`. It prints one line per input: `new`, `updated`,
`unchanged`, `fallback` or `failed`. Unchanged files are detected by
conditional request where the server supports it, otherwise by content, and
are left untouched. Each download is checked before it replaces the
previous copy (zip members, XLSX worksheets, PDF signature, CSV header,
GeoJSON features, and the sha256 where an input pins it); an address CSV
with more than 1 % fewer rows than the previous one is rejected unless
`--force` is given. When the server of a pinned input fails, the input is
taken from a copy with the pinned sha256 (`fallback`, with a warning): the
one on disk, else the one committed in `data/fallback/`, laid out like
`data/raw/` with its own `manifest.json`, whose entry (and so the retrieval
date in the About dialog) it keeps. The past election results are there:
in October 2026, two days before the elections, volby.statistics.sk
answered 404 for all of them, and a release starts with an empty
`data/raw/`. The exit code is 1 if any input failed, except an input marked
`optional` (read by no step: the regional constituency announcements,
records of the sources of the curated regional obvody), whose failure is
only a warning.

`candidates` reads the four MV SR candidate lists and the municipality table
of ZBGIS (level 0, unpacked once into `data/build/`). Every row is matched to
a municipality by name within its okres, giving the 6-digit ŠÚ SR
municipality code (`BA` and `KE` for the cities of Bratislava and Košice);
residences of regional candidates are matched within their kraj. Any row
that matches nothing makes the command fail with a list of all such rows, to
be fixed in `config/overrides.toml`. Candidacies of one person in several
contests are merged by municipality, name and age. The current office
holders (mayors, municipal councillors, regional presidents and councillors)
are rebuilt from the ŠÚ SR final results of the 2022 elections and of every
municipal by-election since, and marked on the 2026 candidacies of the same
person (same area, name and an age that fits); a holder who fits several
persons is marked on none. Substitutes who took a seat later and
resignations without a by-election are in no central dataset and so are
missing. Each holder carries the votes and turnout of the unit the seat was
won in (municipality, kraj, or council obvod of that election), from the
same result tables. The result, with a summary of counts, merges
and incumbents on stdout, is `data/build/candidates.json`; its schema is
described in
`src/election_map_slovakia/candidates.py`, the incumbent rules in
`src/election_map_slovakia/incumbents.py`.

`geo` reads ZBGIS boundary levels 0–2, reprojects them from S-JTSK
(EPSG:5514) to WGS84 and writes to `data/build/geo/` the obce of each okres
at three levels of detail (`okres/<okres>/<lod>.json`), a coarse view for
the lowest zooms (`coarse.json`, with the kraj, okres and obvod labels and
the seats of every regional and city council obvod), the countries around
Slovakia from Natural Earth at two levels of detail, with places for their
names (`neighbours/<lod>.json`), and `index.json` with the zoom band of each
level, okres bounding boxes and file sizes. Every file
is a topology: each border is stored once and coded with the highest
boundary it is part of (obec, okres, kraj, country, regional or city council
obvod), so kraj, okres and obvod borders are exactly the municipal borders
drawn with them. The countries around reach under Slovakia's ZBGIS border,
which the map draws over them, so they meet it at every zoom; Natural
Earth's strip between its border of Slovakia and the ZBGIS one goes to the
nearest neighbour. Obvod membership is read from `data/curated/obvody/` and
must cover every obec of its area exactly once, with as many obvody as the
candidate lists have, so `candidates` must have run first. A municipality
with a council obvod rule set (`data/curated/obvody/oz/`) is cut into its
council obvody: unions of cadastral areas where the rules (or its
addresses) say so, else the Voronoi cells of its address points merged per
obvod and smoothed into plausible areas (lone houses, small islands and
interleaved fragments go to the obvod around them; only a separate village
or a large cluster stays a separate piece), marked approximate; so
`addresses` must have run before `geo`. The command fails
if neighbouring areas overlap or leave gaps after rounding, or if the
countries around leave a gap at Slovakia's border at any level; it prints the
seat totals, obvody with fewer candidates than seats, the measured overlap
and gap areas and the file sizes. `--preview OKRES` also writes SVG previews
of the country, Bratislava and that okres for a visual check. Levels of
detail and the output schema are described in `src/election_map_slovakia/geo.py`.

`addresses` reads the MV SR address register and matches its municipality
names like `candidates` (Bratislava and Košice appear as their districts;
unmatched names fail the command and go to `[address]` in
`config/overrides.toml`). It writes `data/build/addr/index.json`, the search
index of municipalities, street names and parts of municipalities, and one
`<obec>.json` per municipality with every house number and its point, and
the municipality's council status: `single` with its one council obvod,
`address` where it has several council obvody and a rule set
(`data/curated/obvody/oz/<obec>.toml`) that gives every address its obvod
(`ems addresses` fails unless each address lands in exactly one of the
candidate lists' obvody), `pending` where it (or a city district) has
several obvody and no rule set yet, or `none` without a council election.
The addresses of every municipality with several council obvody also go to
`data/build/obvod-addresses/`, the input of the `obvod-rules` jobs. Addresses
without coordinates stay searchable without a point. It checks every point
against the municipality polygon (ZBGIS level 0): points more than 100 m
outside are published without a point, and all points outside are listed
with their distance in `data/build/addresses-outside.tsv`. It
prints the counts, the municipalities pending street rules, the farthest
outliers, a random sample of 100 addresses resolved to their contests, and
the file sizes (raw and gzip). It needs the contests from `candidates`, so
that must have run first. The output schema is described in
`src/election_map_slovakia/addresses.py`.

`build` wipes `dist/` and writes the site from `web/`, the three outputs
above and the configuration; the same inputs give the same bytes. Besides
the geometry and address files it writes the candidates split so that a
place needs at most three small files (municipal contests per okres,
Bratislava and Košice city contests, regional contests per kraj), a
candidate-name search index sharded by two-letter prefix, the UI strings per
language, an app shell per language under `/<lang>/` and a root page that
picks the language (stored choice, browser languages with the aliases from
`config/languages.toml`, then the first fallback). It prints file counts and
sizes (raw and gzip) per group. The code goes to `/assets/<v>/`, the
vendored libraries to `/assets/vendor/<vv>/` and the images to
`/assets/img/<iv>/`, each version a hash of its files, and the app fetches
its JSON with `?v=<data version>`, a hash of the data, so that a release
replaces browsers' copies of what changed and keeps the rest (see "Cache
busting" in the module doc). The layout is described in
`src/election_map_slovakia/build.py`. `serve` serves `dist/` with Python's HTTP server
for local testing, adding the response headers of `dist/_headers` and
answering missing paths with `dist/404.html` and status 404, as Cloudflare
Pages does (without a `404.html`, Pages would answer them with the root
page and status 200).

`check` verifies `dist/` and prints a table of its checks: at most
`file_budget` files and no file above `max_file_bytes` (`config/site.toml`;
Cloudflare Pages allows 20,000 files and 25 MiB per file), valid JSON,
`_headers` within the Pages limits, every file the frontend can request
present (assets, shells and UI strings of every language, geometry shards,
the address and candidate files of every municipality, name shards), every
contest in exactly the area file the frontend looks in, no HTML, JS or CSS
referring to another origin except as a link target (and the live results
origin in the app shells' config, which the CSP's connect-src names), every address point
within its municipality's bounding box, at every level of detail the
borders drawn are the municipalities' own edges, each drawn once, with every
kraj, okres, obvod and the country (merged from the municipalities) bounded
by exactly the lines drawn as its border, and the countries around Slovakia
leave no gap at its border at any level and are named in every language.
It lists the problems and exits
with 1 if there are any. The checks are described in
`src/election_map_slovakia/check.py`.

`results` makes the live results site in `live/`, a Cloudflare Pages
project of its own that the app reads on election night: from volbysr.sk
as the votes are counted (`poll`), from the definitive CSV tables (`final`)
or as dummy data (`fake`); `results serve` and `results deploy` serve and
upload it. Its file format, the sources and the night's steps are in
[results.md](results.md).

## Identifiers

- obec: the 6-digit ŠÚ SR municipality code (ZBGIS `IDN4`, e.g. `528595`
  for Bratislava-Staré Mesto), or `BA` and `KE` for the cities of
  Bratislava and Košice; okres: ZBGIS `IDN3` (the candidate lists' `Kód
  okresu`); kraj: ZBGIS `IDN2`, 1–8
- contest: `<kind>:<area>`, the kind `starosta` (mayor), `oz` (municipal
  council), `predseda` (regional president) or `zsk` (regional council),
  the area an obec, `<obec>/<obvod>`, a kraj or `<kraj>/<obvod>`, e.g.
  `starosta:508438`, `oz:528595/2`, `predseda:8`, `zsk:7/2`
- candidacy: `<contest>#<ballot number>`, e.g. `oz:528595/2#7`; stable, and
  the key of the election results
- person: a short hash of the obec, name and age that merge candidacies
  (`merge_persons` in `src/election_map_slovakia/candidates.py`), corrected
  in `config/overrides.toml`

## Configuration

- `config/site.toml` — the site's own domain (`base_url`, empty until it
  has one), source repository, Cloudflare Pages project, election date,
  live results origin (`live_url`, replaced by the environment variable
  `EMS_LIVE_URL` if set), the days after the polls close that the app polls
  it (`live_days`) and its Pages project, output budgets
- `config/languages.toml` — UI languages with the site's name in each,
  fallback chain, browser aliases
- `config/sources.toml` — allowlist of sources for research, by category,
  the reports the media were selected from, and which categories each
  research language searches
- `config/municipal-domains.toml` — official websites of municipalities and
  regions, which research may cite (category `official`)
- `config/blocklist-konspiratori.txt` — dated snapshot of konspiratori.sk
- `config/inputs.toml` — official input files, their URLs and checks
- `config/certs/` — intermediate CA certificates some input servers omit
- `config/overrides.toml` — municipality-name fixes (candidate lists and
  address register) and person-merge corrections
- `config/parties.toml` — every party of the candidate lists: short form,
  official name (Ministry of Interior register), optional logo in
  `web/img/parties/` with its source and license; `build` rejects 2026
  candidacies of parties missing here

Hand-curated inputs, committed:

- `data/curated/obvody/zsk-<kraj>.toml` — regional council obvody (seats and
  member okresy or obce), transcribed from each region's decision
- `data/curated/obvody/BA.toml`, `KE.toml` — city council obvody of
  Bratislava and Košice (seats and member city districts)
- `data/curated/translations/<lang>.json` — machine translations from the
  `translation` jobs: `ui` (key → the English `src` translated and its
  `text`), `occupations` (Slovak → translation) and `research` (claim or
  quote → translation)
- `data/curated/obvody/oz/<obec>.toml` — council obvody of a municipality by
  address (streets, house numbers, parts, cadastral areas), transcribed by
  an `obvod-rules` job; `data/curated/cache/` — the official documents they
  were transcribed from, by sha256, and the cached copies of the pages
  research cites
- `data/curated/research/` — what the `research` jobs found per candidate
- `data/fallback/` — copies of pinned inputs, for when their server fails
  (see `fetch` above)

The obvod files name their source document (`source`) and decision date
(`date`).
