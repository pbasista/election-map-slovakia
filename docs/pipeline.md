# The pipeline

A Python pipeline turns official open data into the static site in `dist/`.
Its command is `ems` (**E**lection **M**ap **S**lovakia).
`fetch` downloads the inputs into `data/raw/`;
the steps after it write `data/build/`,
and `build` assembles the site from that, `web/` and `config/`.

## Commands

```sh
uv run ems fetch                     # download every input
uv run ems fetch --only addresses    # just the named inputs
uv run ems fetch --force             # ignore server validators
uv run ems candidates                # data/build/candidates.json
uv run ems addresses                 # data/build/addr/, data/build/obvod-addresses/
uv run ems geo                       # data/build/geo/
uv run ems geo --preview 806         # plus SVG previews in data/build/preview/
uv run ems basemap                   # data/build/base/
uv run ems build                     # dist/
uv run ems check                     # verify dist/ before deploying
uv run ems make                      # candidates, addresses, geo, basemap, results, build, check
uv run ems make --force              # also redo the steps that are up to date
uv run ems serve --port 8000         # http://127.0.0.1:8000/
uv run ems results poll --deploy     # election night: volbysr.sk → results → site → Pages
uv run ems results fake mid          # dummy results for testing the app
```

`ems job …` and `ems research …` are in [agent-jobs.md](agent-jobs.md),
`ems results …` in [results.md](results.md).

## How the steps run

### `make`

To rebuild the site after `fetch`
(or after changing `config/`, `data/curated/` or `web/`),
run `uv run ems make` and then `uv run ems serve`.

`make` runs `candidates`, `addresses`, `geo`, `basemap`, `results`, `build`
and `check` in this order, each as if run on its own.
It stops at the first that fails,
naming it and the steps it did not run.
`results` is a step of `make` only ([below](#results)).

### Skipping what is up to date

`candidates`, `addresses`, `geo`, `basemap` and `results`
skip their work when nothing they depend on
has changed since they last succeeded.
They record in `data/build/<step>.stamp.json` the sha256 of:

- their input files
  (downloads, the election's `obvody/`, `data/build/candidates.json`);
- the configuration they use (`config/inputs.toml` entries, overrides);
- their code: their modules and the package modules these import, the CLI,
  and the Python, NumPy, Shapely/GEOS and pyproj/PROJ versions
  (for `basemap` also pyosmium's and libosmium's).

A step runs again when any of it differs, when an output is missing,
or with `--force`,
and says which it was, or that it is up to date.
A comment added to a TOML file reruns the steps
that read the file as text (curated obvody)
but not those that read its values (overrides).
`geo --preview` always runs.
`build` and `check` always run (5 s each);
an up-to-date `make` takes about 15 s instead of 2 minutes.

### Worker processes

`addresses`, `geo`, `basemap` and `check` split their work into pieces
that do not depend on each other
(obce, levels of detail, okresy, parts of the site)
and run them in worker processes, one per CPU
(`parallel.py`),
the longest first where their length can be told beforehand
(an obec's cut by the size of its addresses file),
so that no worker is left with a long piece when the others are done.
The results are put together in order,
so the output is the same as if the pieces ran one by one.
On 8 CPUs a full `make --force` takes about 2 minutes;
`geo` needs up to 1.8 GB of memory, `basemap` 3.2 GB.

### Gzip sizes

`addresses`, `basemap` and `build` report the gzip -9 size of what they
write.
Each keeps the sizes it measured last by the SHA-256 of each file
(`data/build/gzip-sizes/<step>.json`)
and compresses only the contents it has not seen:
of the site's 630 MB nearly all are the same from one build to the next,
and compressing them took 9 s of every build.

### Progress and summaries

Every command but `serve` reports on stderr what it is doing:
each part as it starts,
a running count or percentage for the long ones
(downloads, the address register, writing and measuring files),
and how long each part took.
On a terminal a part's count updates in place.
The summaries described below go to stdout,
so `uv run ems geo > geo.txt` keeps just the summary.

## Steps

### `fetch`

Downloads the files declared in `config/inputs.toml`
(the official election and boundary files, Natural Earth's countries
and the OpenStreetMap extract of Slovakia)
into `data/raw/<name>/`,
and records URL, sha256, size and retrieval time
in `data/raw/manifest.json`.
It prints one line per input:
`new`, `updated`, `unchanged`, `fallback` or `failed`.

- **Unchanged files** are detected by conditional request
  where the server supports it, otherwise by content,
  and are left untouched.
- **Each download is checked** before it replaces the previous copy:
  zip members, XLSX worksheets, PDF signature, CSV header,
  GeoJSON features, the OSM PBF header,
  and the sha256 where an input pins it.
  An address CSV with more than 1 % fewer rows than the previous one
  is rejected unless `--force` is given.
- **Fallback.** When the server of a pinned input fails,
  the input is taken from a copy with the pinned sha256
  (`fallback`, with a warning):
  the one on disk, else the one committed in `data/fallback/`.
  That directory is laid out like `data/raw/`
  with its own `manifest.json`,
  whose entry (and so the retrieval date in the About dialog) it keeps.
  The OSM extract (311 MiB) is not committed there.
  The past election results are:
  in October 2026, two days before the elections,
  volby.statistics.sk answered 404 for all of them,
  and a release starts with an empty `data/raw/`.
- **Exit code** 1 if any input failed,
  except an input marked `optional`, whose failure is only a warning.
  Optional inputs are read by no step:
  the regional constituency announcements,
  records of the sources of the curated regional obvody.

### `candidates`

Reads the four MV SR candidate lists
and the municipality table of ZBGIS
(level 0, unpacked once into `data/build/`),
and writes `data/build/candidates.json`,
with a summary of counts, merges and incumbents on stdout.
Its schema is described in `src/election_map_slovakia/candidates.py`,
the incumbent rules in `src/election_map_slovakia/incumbents.py`.

- **Municipalities.**
  Every row is matched to a municipality by name within its okres,
  giving the 6-digit ŠÚ SR municipality code
  (`BA` and `KE` for the cities of Bratislava and Košice);
  residences of regional candidates are matched within their kraj.
  Any row that matches nothing makes the command fail
  with a list of all such rows, to be fixed in `config/overrides.toml`.
- **Persons.**
  Candidacies of one person in several contests
  are merged by municipality, name and age.
- **Current office holders**
  (mayors, municipal councillors, regional presidents and councillors)
  are rebuilt from the ŠÚ SR final results of the 2022 elections
  and of every municipal by-election since.
  They are marked on the 2026 candidacies of the same person
  (same area, name and an age that fits);
  a holder who fits several persons is marked on none.
  Substitutes who took a seat later
  and resignations without a by-election
  are in no central dataset and so are missing.
- **Past turnout.**
  Each holder carries the votes and turnout of the unit the seat was won in
  (municipality, kraj, or council obvod of that election),
  from the same result tables.
  These also give each municipality's 2022 turnout per okrsok:
  `build` sums it over the okrsky of each 2026 council obvod
  where they are known and numbered as then.

### `addresses`

Reads the MV SR address register
and matches its municipality names like `candidates`
(Bratislava and Košice appear as their districts;
unmatched names fail the command and go to `[address]`
in `config/overrides.toml`).
It needs the contests from `candidates`, so that must have run first.
The output schema is described in `src/election_map_slovakia/addresses.py`.

It writes to `data/build/addr/`:

- `index.json`: the search index of municipalities,
  street names and parts of municipalities;
- one `<obec>.json` per municipality
  with every house number and its point,
  and the municipality's council status:
  - `single`, with its one council obvod;
  - `address`, where it has several council obvody and a rule set
    (`obvody/oz/<obec>.toml` of the election)
    that gives every address its obvod
    (`ems addresses` fails unless each address lands in exactly one
    of the candidate lists' obvody);
  - `pending`, where it (or a city district) has several obvody
    and no rule set yet;
  - `none`, without a council election.

Further:

- **Okrsky.**
  Where the okrsky are known by address (those `geo` draws),
  every street and part in `<obec>.json` also says its okrsok
  (`okrsok`, or `okrsky` per number).
  A rule set that leaves an address in no okrsok or in two is reported
  and its municipality written without okrsky.
- **Job input.**
  The addresses of every municipality
  with several council obvody or several okrsky (`units-oso2026`)
  also go to `data/build/obvod-addresses/`,
  the input of the `obvod-rules` and `okrsok-rules` jobs.
- **Points.**
  Addresses without coordinates stay searchable without a point.
  Every point is checked against the municipality polygon (ZBGIS level 0):
  points more than 100 m outside are published without a point,
  and all points outside are listed with their distance
  in `data/build/addresses-outside.tsv`.

It prints the counts, the municipalities pending street rules,
the farthest outliers,
a random sample of 100 addresses resolved to their contests,
and the file sizes (raw and gzip).

### `geo`

Reads ZBGIS boundary levels 0–2,
reprojects them from S-JTSK (EPSG:5514) to WGS84,
and writes to `data/build/geo/`:

- `okres/<okres>/<lod>.json`: the obce of each okres
  at three levels of detail;
- `coarse.json`: a coarse view for the lowest zooms,
  with the kraj, okres and obvod labels
  and the seats of every regional and city council obvod;
- `neighbours/<lod>.json`: the countries around Slovakia from Natural Earth
  at two levels of detail, with places for their names;
- `okrsky/<okres>/<lod>.json`: the okrsky, where known (below);
- `index.json`: the zoom band of each level, okres bounding boxes,
  and the okrsky files (`okrsky`).

Levels of detail and the output schema
are described in `src/election_map_slovakia/geo.py`.

**Topology.**
Every file is a topology:
each border is stored once and coded with the highest boundary
it is part of
(obec, okres, kraj, country, regional or city council obvod),
so kraj, okres and obvod borders
are exactly the municipal borders drawn with them.
The countries around reach under Slovakia's ZBGIS border,
which the map draws over them, so they meet it at every zoom;
Natural Earth's strip between its border of Slovakia and the ZBGIS one
goes to the nearest neighbour.

**Obvody.**
Obvod membership is read from `obvody/` in the election's data
(`data/curated/elections/<election day>/`, see [Curated data](#curated-data)).
It must cover every obec of its area exactly once,
with as many obvody as the candidate lists have,
so `candidates` must have run first.
A municipality with a council obvod rule set (`obvody/oz/` there)
is cut into its council obvody:

- unions of cadastral areas, where the rules (or its addresses) say so;
- else the Voronoi cells of its address points, merged per obvod
  and smoothed into plausible areas, marked approximate.
  Lone houses, small islands and interleaved fragments
  go to the obvod around them;
  only a separate village or a large cluster stays a separate piece.

So `addresses` must have run before `geo`.

**Okrsky.**
Where a rule set also gives the okrsky of each obvod and their rules,
`geo` draws the okrsky within the obvody
(unions of cadastral areas where they allow,
else from the address points like the obvody);
likewise the okrsky of a municipality with one council obvod
(`okrsky/<obec>.toml`) within the whole municipality.
It cuts them from the municipality's map features
at every level of detail
and writes them per okres, beside the municipalities.
It fails if an address is in no okrsok or in two,
or the okrsky do not tile their obvod or their municipality on the map.

**Checks and summary.**
The command fails if neighbouring areas overlap
or leave gaps after rounding,
or if the countries around leave a gap at Slovakia's border at any level.
It prints the seat totals,
obvody with fewer candidates than seats,
the measured overlap and gap areas, and the file sizes.
`--preview OKRES` also writes SVG previews
of the country, Bratislava and that okres for a visual check.

### `basemap`

Reads the OpenStreetMap extract of Slovakia with pyosmium
and writes the faint base map
that the app draws under the election colours
to `data/build/base/`.
The classes and levels are described
in `src/election_map_slovakia/basemap.py`.

- **Source.**
  Geofabrik's extract of 1 January 2026, pinned:
  Geofabrik keeps each year's first extract for good.
  © OpenStreetMap contributors, ODbL 1.0.
- **Content.**
  The roads by class
  (motorway, expressway, primary, secondary, tertiary, minor streets),
  the railways and trams,
  the rivers, canals and the streams of a named course of at least 5 km,
  the water areas (lakes, reservoirs, river areas, merged into one)
  and the buildings (`building=*`, closed ways and multipolygons).
- **Left out.**
  ZBGIS has no open download of its roads and waters.
  Forests and built-up areas are left out:
  a tint over that much of the map would shift the results' colour steps.
- **Files.**
  For each level of detail of the shards,
  one file per okres, clipped to the okres (ZBGIS level 1),
  with the classes, simplification and least water area of that level
  (`okres/<okres>/<lod>.json`: minor streets and streams only from lod 1,
  ramps too).
  A light `coarse.json` serves the country view
  (motorways, expressways, rivers of a course of 50 km or more,
  lakes of 1 km² or more).
  Waters reach 1 km beyond Slovakia's border,
  which the border rivers follow.
  The files are topologies like the geo files
  (each line an arc coded with its class,
  each water ring an arc of a feature),
  their okresy and the shards' zoom bands in `index.json`.
- **Buildings.**
  One file per obec (ZBGIS level 0, the shards' obce),
  `obec/<obec>.json`, which the app draws from zoom 16
  for the obce in view;
  `index.json` lists them as `buildings: {zoom, obce}`.
  A building goes whole to the obec
  that holds the mean of its outer ring's vertices,
  else to the nearest within 50 m;
  the rest lie abroad.
  The outlines are as mapped, only rounded to 10⁻⁵°
  (about a metre; simplifying by a metre more
  would save a tenth of the vertices but cut the corners of small houses);
  rings left with fewer than three vertices or no area are dropped.
  A file is `{scale: 100000, counts: [n, …], xy: [x, y, dx, dy, …]}`:
  `counts` are the vertices of each ring,
  `xy` all rings' vertices in turn as one sequence of grid steps
  (`round(lon × scale)`, `round(lat × scale)`, the first absolute),
  each ring open.
  Each building is its outer ring, counter-clockwise,
  directly followed by its holes, clockwise,
  so that the nonzero rule fills it;
  the buildings follow a Hilbert curve, so the steps stay short.
- **Summary.**
  It prints, per level, the lines per class, water areas, vertices
  and sizes (raw and gzip):
  239 files, 17 MB, 6.2 MB gzipped, the largest 120 KiB gzipped;
  then the same of the buildings:
  2.6 million in 2,927 files, 14.8 million vertices,
  81 MiB, 26 MiB gzipped, the largest 850 KiB (250 KiB gzipped).
  It takes about 26 s:
  three workers read the extract side by side
  (the lines, the water and multipolygon areas, the buildings' ways),
  then the workers place the buildings in their obce, a share each
  (gzip -9 of the 81 MiB, for the summary, takes another 5 s
  for the files not measured before: see [Gzip sizes](#gzip-sizes)).

### `results`

A step of `make` only.
It writes the election's results,
`data/build/results/<election day>/`,
from the definitive results packages
pinned as the inputs `results-oso<year>` and `results-osk<year>`
(the year of the election day),
as of their data, so that the same inputs give the same files.
Without them it leaves the directory as `ems results` left it.

`ems results` writes that directory too:
from volbysr.sk as the votes are counted (`poll`),
from the definitive CSV tables (`final`)
or as dummy data (`fake`);
`results deploy` builds the site with them and uploads it.
`build` copies the directory to `dist/results/<election day>/`,
where the app reads it; each election has its own.
The file format, the sources and the night's steps
are in [results.md](results.md).

### `build`

Wipes `dist/` and writes the site from `web/`,
the outputs of the steps above,
the election's results (if there) and the configuration;
the same inputs give the same bytes.
It prints file counts and sizes (raw and gzip) per group.
The layout is described in `src/election_map_slovakia/build.py`.

Besides the geometry, base map (`base/`) and address files it writes:

- the candidates, split so that a place needs at most three small files:
  municipal contests per okres,
  Bratislava and Košice city contests,
  regional contests per kraj;
- a candidate-name search index, sharded by two-letter prefix;
- the UI strings per language;
- an app shell per language under `/<lang>/`;
- a root page that picks the language:
  the stored choice, the browser languages
  with the aliases from `config/languages.toml`,
  then the first fallback.

**Versioned paths.**
The code goes to `/assets/<v>/`,
the vendored libraries to `/assets/vendor/<vv>/`
and the images to `/assets/img/<iv>/`,
each version a hash of its files.
The app fetches its JSON with `?v=<data version>`, a hash of the data.
So a release replaces browsers' copies of what changed
and keeps the rest
(see "Cache busting" in the module doc,
and [Caching in deploy.md](deploy.md#caching)).

### `serve`

Serves `dist/` with Python's HTTP server for local testing
(`--host`, `--port`; default <http://127.0.0.1:8000/>).
It adds the response headers of `dist/_headers`
and answers missing paths with `dist/404.html` and status 404,
as Cloudflare Pages does
(without a `404.html`, Pages would answer them
with the root page and status 200).

### `check`

Verifies `dist/` and prints a table of its checks.
It lists the problems and exits with 1 if there are any.
The checks are described in `src/election_map_slovakia/check.py`:

- **Budgets:** at most `file_budget` files
  and no file above `max_file_bytes` (`config/site.toml`;
  Cloudflare Pages allows 20,000 files and 25 MiB per file).
- **Formats:** valid JSON; `_headers` within the Pages limits.
- **Completeness:** every file the frontend can request is present:
  assets, shells and UI strings of every language,
  geometry shards and polling district files,
  the base map files of `base/index.json`,
  the address and candidate files of every municipality, name shards.
- **Contests:** every contest in exactly the area file
  the frontend looks in.
- **Origin:** no HTML, JS or CSS refers to another origin
  except as a link target
  (the CSP's connect-src is `'self'` alone).
- **Results:** the results of every election day in `results/`
  keep their format
  and list exactly their files with their hashes.
- **Addresses:** every address point within its municipality's bounding box;
  every address with its polling district exactly where the map draws them.
- **Borders:** at every level of detail
  the borders drawn are the municipalities' own edges, each drawn once,
  with every kraj, okres, obvod and the country
  (merged from the municipalities)
  bounded by exactly the lines drawn as its border;
  the polling districts of each municipality tile it.
- **Neighbours:** the countries around Slovakia
  leave no gap at its border at any level
  and are named in every language.
- **Base map:** it has the shards' levels of detail and okresy,
  `base/` holds no file its index does not let the app request,
  and each file only the line classes of its level.

## Identifiers

| Identifier | Form | Examples |
|---|---|---|
| obec | the 6-digit ŠÚ SR municipality code (ZBGIS `IDN4`), or `BA` and `KE` for the cities of Bratislava and Košice | `528595` (Bratislava-Staré Mesto) |
| okres | ZBGIS `IDN3` (the candidate lists' `Kód okresu`) | `806` |
| kraj | ZBGIS `IDN2`, 1–8 | `8` |
| contest | `<kind>:<area>`; kind `starosta` (mayor), `oz` (municipal council), `predseda` (regional president) or `zsk` (regional council); area an obec, `<obec>/<obvod>`, a kraj or `<kraj>/<obvod>` | `starosta:508438`, `oz:528595/2`, `predseda:8`, `zsk:7/2` |
| candidacy | `<contest>#<ballot number>`; stable, and the key of the election results | `oz:528595/2#7` |
| person | a short hash of the obec, name and age that merge candidacies (`merge_persons` in `src/election_map_slovakia/candidates.py`), corrected in `config/overrides.toml` | `9a9a5bf4bc1d` |

## Configuration

| File | What it holds |
|---|---|
| `config/site.toml` | The site's own domain (`base_url`, empty until it has one), source repository, Cloudflare Pages project, election date, the polls' hours, whether the app polls the results (`live`) and for how many days after the polls close (`live_days`; at any time in a build with `EMS_RESULTS_ANYTIME=1` in the environment), output budgets |
| `config/languages.toml` | UI languages with the site's name in each, fallback chain, browser aliases |
| `config/sources.toml` | Allowlist of sources for research, by category; the reports the media were selected from; which categories each research language searches |
| `config/municipal-domains.toml` | Official websites of municipalities and regions, which research may cite (category `official`) |
| `config/blocklist-konspiratori.txt` | Dated snapshot of konspiratori.sk |
| `config/inputs.toml` | Official input files, their URLs and checks |
| `config/certs/` | Intermediate CA certificates some input servers omit |
| `config/overrides.toml` | Municipality-name fixes (candidate lists and address register) and person-merge corrections |
| `config/parties.toml` | Every party of the candidate lists: short form, official name (Ministry of Interior register), optional logo in `web/img/parties/` with its source and licence; `build` rejects 2026 candidacies of parties missing here |

## Curated data

Hand-curated inputs, committed:

- `data/curated/elections/<election day>/`:
  what the state sets anew for each election,
  kept per election (the day of `config/site.toml` `election`),
  so that a later election adds a directory of its own
  instead of changing this one's.
  The obvod files name their source document (`source`),
  its title as the ballots show it (`title`)
  and the decision date (`date`).
  - `obvody/zsk-<kraj>.toml`: regional council obvody
    (seats and member okresy or obce),
    transcribed from each region's decision.
  - `obvody/BA.toml`, `KE.toml`: city council obvody
    of Bratislava and Košice (seats and member city districts).
  - `obvody/oz/<obec>.toml`: council obvody of a municipality by address
    (streets, house numbers, parts, cadastral areas),
    transcribed by an `obvod-rules` job,
    and its okrsky with their rules, added by an `okrsok-rules` job.
  - `okrsky/<obec>.toml`: okrsky of a municipality with one council obvod,
    by address, transcribed by an `okrsok-rules` job;
    `okrsky/not-found.json` lists the municipalities
    whose okrsky document was not found.
- `data/curated/translations/<lang>.json`:
  machine translations from the `translation` jobs:
  `ui` (key → the English `src` translated and its `text`),
  `occupations` (Slovak → translation)
  and `research` (claim or quote → translation).
- `data/curated/cache/`:
  the official documents the obvody and okrsky were transcribed from,
  by sha256, and the cached copies of the pages research cites.
- `data/curated/research/`:
  what the `research` jobs found per candidate.
- `data/fallback/`:
  copies of pinned inputs, for when their server fails
  (see [`fetch`](#fetch)).
