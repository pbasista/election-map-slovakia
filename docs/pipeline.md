# The pipeline

A Python pipeline turns official open data into the static site in `dist/`.
Its command is `ems` (**E**lection **M**ap **S**lovakia).
`fetch` downloads the inputs into `data/raw/`;
the steps after it write `data/build/`,
and `build` assembles the site from that, `web/` and `config/`,
in parts that are deployed separately
([deploy.md](deploy.md)).

## Elections

The site shows several elections,
each listed in `config/elections.toml` under its slug,
its name in URLs
(`2026`, a by-election `2026-03`, the others `2024-prezident`,
`2023-referendum`, `2023-nrsr`, `2024-ep`).
Each is of one `kind`, which says what its contests can be
(`src/election_map_slovakia/contests.py`):

| `kind` | Contests |
|---|---|
| `municipal-regional` | the regular elections: mayors, councils, regional presidents and councils |
| `by-election` | the same, only where held |
| `presidential` | `prezident:SK/1`, `prezident:SK/2` (the rounds) |
| `referendum` | `referendum:SK/<question>` |
| `parliament`, `european` | the party contest `nrsr:SK` (`ep:SK`) and each party's list `nrsr:SK/<party>` |

An election's table gives its day, the polls' hours,
whether the app polls its results (`live`, `live_days`),
what only its kind has
(`second_round`, `questions`, `seats`, `threshold`,
`coalition_thresholds`, `preferences`, `preference_quota`),
and the inputs of `config/inputs.toml` its steps read:
the candidate lists (`candidates`, with the `format` they are read in;
`mvsr` names the four MV SR lists by contest kind,
and `units` ŠÚ SR's territorial division, which says what is held where;
none for a referendum),
the results the office holders are rebuilt from
(`incumbents`, optional, regular elections only),
the territorial division (`units`, optional but for regular elections:
without it no okrsky are counted or drawn; a country-wide election
reads it from its own package, format `volbysr`),
the final results once published
(`results`), the address register (`addresses`), the ZBGIS levels 0 to 2
(`zbgis`), the OpenStreetMap extract (`osm`) and the records of sources
no step reads, such as its regional obvod documents (`records`).
The file's header comments document every field.
Adding an election is adding a table there and its inputs
([elections.md](elections.md)).
No two elections may share a day.

Two elections stand out:

- **the home election**, the one `/<lang>/` shows (`Config.home`):
  the newest by day, an upcoming one included,
  so that the site opens on the most recent or the upcoming election,
  but never a by-election,
  which is held in a few places only and concerns few visitors;
- **the latest**, the newest `municipal-regional` election
  (`Config.latest`, of which there must be one),
  which the jobs, research and reuse of rules default to,
  as do the commands' `--election`;
  visitors meet it only where another election's page
  names what it takes from it (research reused from it,
  About's "What comes from 2026"),
  never as the election the site opens on.

Each election has

- its curated data in `data/curated/elections/<day>/`
  (obvody, okrsky, documents, not-found lists);
- what the steps make of it in `data/build/<day>/`:
  `candidates.json`, `links/`, `addr/`, `obvod-addresses/`,
  `addresses-outside.tsv`, `geo/`, `results/` (the final results),
  `crosswalk/`, and the steps' stamps and gzip memos;
  on an election night also `live/`, the live results `ems results`
  writes, which no step reads nor writes;
- its pages `/<lang>/<slug>/` in the app
  and its bundles `dist/map/<slug>/` (`geo/`, `addr/`)
  and `dist/data/<slug>/` (`data/`, `i18n/`),
  its final results in `dist/results/<day>/`
  and its live results in `dist/live/<day>/` ([`build`](#build)).

Each OpenStreetMap extract an election names (`osm`) has a base map,
which every election on it shows:
`data/build/base/<extract>/base/` with its stamp and gzip memo
([`basemap`](#basemap)), and `dist/base/<extract>/`.

The steps from `candidates` to `results` run for every election,
or with `--election DAY` (its day or slug) for one;
`basemap` for every extract, or for that election's;
`build` and `check` for the whole site.
The GeoPackages unpacked from the ZBGIS inputs
stay in `data/build/`:
they are the inputs', shared by the elections that read them.

## Commands

```sh
uv run ems fetch                     # get every input
uv run ems fetch --only addresses    # just the named inputs
uv run ems fetch --force             # ignore server validators
uv run ems inputs update addresses   # pin what the source serves now
uv run ems inputs publish            # upload new pinned files to the input store
uv run ems candidates                # data/build/<day>/candidates.json
uv run ems links                     # data/build/<day>/links/<earlier slug>.json
uv run ems addresses                 # data/build/<day>/addr/, …/obvod-addresses/
uv run ems geo                       # data/build/<day>/geo/
uv run ems geo --preview 806         # plus SVG previews in data/build/<day>/preview/
uv run ems basemap                   # data/build/base/<extract>/base/, once per extract
uv run ems build                     # dist/, in parts
uv run ems build --deployed          # dist/app/ for the deployed data parts
uv run ems check                     # verify dist/ before deploying
uv run ems make                      # candidates, links, addresses, geo, basemap, results, build, check
uv run ems make --election 2026      # the steps up to results for that election (and its extract) only
uv run ems make --force              # also redo the steps that are up to date
uv run ems serve --port 8000         # http://127.0.0.1:8000/
uv run ems data lock                 # data/published.toml, the data parts' keys
uv run ems data lock --check         # fail if data/published.toml is stale
uv run ems data projects --create     # create the Pages projects the site lacks
uv run ems data status               # which data parts are not deployed
uv run ems data deploy               # deploy those from dist/
uv run ems record check              # fail if data/outputs.toml lacks the commit's step inputs
uv run ems record compare            # which outputs in data/build/ are not those recorded
uv run ems results poll --deploy     # election night: volbysr.sk → live results → Pages
uv run ems results fake mid          # dummy live results for testing the app
```

`ems job …` and `ems research …` are in [agent-jobs.md](agent-jobs.md),
`ems results …` in [results.md](results.md).

## How the steps run

### `make`

To rebuild the site after `fetch`
(or after changing `config/`, `data/curated/` or `web/`),
run `uv run ems make` and then `uv run ems serve`.

`make` runs `candidates`, `links`, `addresses`, `geo`, `basemap`, `results`,
`build` and `check` in this order, each as if run on its own.
It stops at the first that fails,
naming it and the steps it did not run.
`results` is a step of `make` only ([below](#results)).

### Skipping what is up to date

`candidates`, `links`, `addresses`, `geo`, `basemap` and `results`
skip their work when nothing they depend on
has changed since they last succeeded.
They record in `data/build/<day>/<step>.stamp.json`
(`basemap` in `data/build/base/<extract>/`)
their inputs, in parts:

- **code**: the sha256 of the source of their modules
  and of the package modules these import;
  of the CLI, the step's own functions and the CLI definitions they use,
  with the package modules those call
  (so a change to another step's wiring, or the package version a release
  bumps, reruns nothing);
- **python**: Python's `major.minor`;
- **libraries**: the versions of the libraries in `uv.lock`
  (GEOS, PROJ and libosmium come with the wheels of Shapely, pyproj and
  pyosmium);
- **pins**: each download by its entry in `config/inputs.toml`
  with its sha256 pin, which `ems fetch` makes the file have
  (the file itself is not read again;
  an input not pinned yet counts by its file);
- **curated**: the curated files and directories they read
  (the election's `obvody/`, okrsky files, curated lists);
- **config**: the configuration they use (the election's entries in
  `config/elections.toml`, its overrides, the links' corrections,
  the coalitions of `config/parties.toml`), as canonical JSON;
- **upstream**: the digest of the output of each step they read
  (below).

With them the stamp records the sha256 of the step's output
over the names and contents of its files,
and a digest of their sizes and modification times:
while those are the same, so is the output,
which is then not read again (as git's index tells a file unchanged;
a file modified within 2 s of the check is read anyway).
An up-to-date `make` thus stats the 123,000 output files
and reads only those of outputs whose files changed since.

A step runs again when an input differs, when an output is missing
or is not what the step wrote, or with `--force`,
and says which it was, or that it is up to date
(unless the output record says it is: [below](#the-output-record)).
A comment added to a TOML file reruns the steps
that read the file as text (curated obvody)
but not those that read its values (overrides).
`geo --preview` always runs.
`build` and `check` always run (10 and 9 s for 25 elections);
an up-to-date `make` takes about 26 s,
42 s the first time after every step ran (it reads their new output once).
Running another Python `major.minor` than `.python-version` pins
(3.15, the release's, for `uv run`) reruns every step,
and its record entries are never those of the commit.

Each step's outputs are what it makes of its inputs alone:

| Step | Outputs (below the stamp's directory) |
|---|---|
| `candidates` | `candidates.json` |
| `links` | `links/` |
| `addresses` | `addr/`, `addresses-outside.tsv`, `obvod-addresses/` |
| `geo` | `geo/` |
| `basemap` | `base/` |
| `results` | `results/`, and `crosswalk/<earlier slug>.json` for each earlier election its results are compared with (2022: 2018 and 2017) |

A file is written whole and a directory replaced whole
(`output.replacing`), so nothing of a run before stays in them.
Not outputs: the gzip sizes a step measured (`gzip-sizes/`, a memo),
`geo`'s previews, the caches of `data/build/shared/`.

A step reads the outputs of the steps before it:

| Step | Upstream outputs |
|---|---|
| `links` | `candidates` of its election and of every earlier one |
| `addresses` | `candidates` |
| `geo` | `candidates`, `addresses` (`obvod-addresses/`) |
| `results` | `candidates`, `geo`; for each earlier election compared with, its own `links`, the `addresses` of both and the earlier one's `results` |

each by the digest of that output as it is on disk.
A step that reads one it does not declare would stay skipped
where it changed;
`tests/test_stamp.py` lists them.

What each package module imports is found by parsing it
(a third of a second for a step's modules)
and kept in `data/build/shared/stamp/imports.json`
by the SHA-256 of its source,
so that a command parses only the modules changed since.

`basemap` depends on nothing of an election but its extract and ZBGIS
levels 0 and 1 ([`basemap`](#basemap)), which elections share:
25 elections read 10 extracts.
So it runs once per extract, for every election on it,
and `config/elections.toml` must give the elections on one extract
the same ZBGIS levels 0 and 1 (loading it fails otherwise).

### The output record

A stamp is of one machine:
after a pull of a commit that changes a step's code,
every machine would run the step again
even where the change left its output as it was.
`data/outputs.toml`, committed, records for each step
and each election (`basemap`: each extract)
the digest of its inputs, of each part of them, and of its output:

```toml
[geo."2026-10-24"]
inputs = "…"
outputs = "…"
parts = { code = "…", config = "…", curated = "…", libraries = "…", pins = "…", python = "3.15", upstream = "…" }
```

Only the steps write it. For each step, `make`
(and each step's own command):

1. skips the step when its stamp says it is up to date;
2. else skips it when the record has its inputs
   and its output on disk is the one recorded,
   writing its stamp with these inputs
   ("up to date per data/outputs.toml");
3. else runs it, and then:
   where the record has no entry for it or other inputs,
   writes its entry (inputs and output);
   where the record has its inputs but another output,
   warns and leaves the entry as it is:
   the step's output varies (nondeterminism) or the entry is wrong
   (remove it and run the step again to record its output).

`--force` always runs the step, and records as in 3.
Where nothing runs the record stays as it is.
Writing it drops the entries of elections no longer configured.
So a commit that changes a step's code
comes with the entries `make` wrote;
a collaborator who pulls it skips the step
where its output on disk is the one recorded.

`ems record check`, which CI runs, computes every step's inputs
from the commit alone, in seconds, without `data/raw/` or `data/build/`:
the code, `uv.lock`, the Python of `.python-version`,
the pins, the configuration, the curated data,
and each upstream output as the record has it.
It fails naming each step, election and part of the inputs
not as recorded: a change committed without running `make`.

`ems record compare` says which outputs in `data/build/` are not
those recorded, and whether the step's inputs there are;
a release runs it ([deploy.md](deploy.md#what-runs-when)).

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
`geo` starts its workers once for all its stages
(starting them takes about a third of a second).
On 8 CPUs (4 fast, 4 slow) a full `make --force` of 25 elections takes
about 23 minutes from nothing cached (`data/build/shared/` emptied), 14 of
them `geo` (13 min 40 s), mostly cutting municipalities by street blocks,
which later runs take from the cache;
`geo` needs up to 2.3 GB of memory with its workers, `basemap` about 3 GB.

### Gzip sizes

`addresses`, `basemap` and `build` report the gzipped size of what they
write: libdeflate's at level 9 (the `deflate` package),
which on 2026's bundles (200 MB) takes 10 CPU-s where zlib's `gzip -9`
takes 36, for 2.7 % fewer bytes
(zlib-ng's level 9, within 0.2 % of zlib's, takes 12).
The sizes are only reported.
Each keeps the sizes it measured last by the SHA-256 of each file,
with the compressor that measured them
(`data/build/<day>/gzip-sizes/<step>.json`, for `basemap`
`data/build/base/<extract>/gzip-sizes/basemap.json`, for `build`
`data/build/gzip-sizes/build.json`)
and compresses only the contents it has not seen:
of the site's 2.9 GB nearly all are the same from one build to the next.

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

Gets the files declared in `config/inputs.toml`
(the official election and boundary files, Natural Earth's countries
and the OpenStreetMap extract of Slovakia)
into `data/raw/<name>/`,
and records URL, sha256, size and retrieval time
in `data/raw/manifest.json`.
It prints one line per input:
`new`, `updated`, `unchanged` or `failed`,
with where the file came from.

- **Pinned inputs.**
  Every input pins its file by `sha256`
  and the day it was downloaded (`retrieved`,
  which the About dialog shows).
  A pinned input is taken from the disk
  where `data/raw/manifest.json` records it with the pinned digest
  (`unchanged … on disk`, no network)
  or, where the manifest does not, where the file there has the pinned
  digest (`found on disk`: a file copied into `data/raw/<name>/` by hand),
  else from the [input store](#the-input-store) (`from the store`),
  else from its source (`from the source`);
  the digest is checked in every case.
  An input whose page changes on every request
  (an ASP.NET page's hidden `__VIEWSTATE`) never matches its pin
  from the source: only the disk and the store have it.
  So a release, which starts with an empty `data/raw/`,
  gets the same files though a server has since changed
  or removed them
  (in October 2026, two days before the elections,
  volby.statistics.sk answered 404 for all the past results).
- **Unpinned inputs** are downloaded from their source;
  unchanged files are detected by conditional request
  where the server supports it, otherwise by content,
  and are left untouched.
- **Each download is checked** before it replaces the previous copy:
  zip members, XLSX worksheets, PDF signature, CSV header,
  GeoJSON features, the OSM PBF header,
  and the sha256 where an input pins it.
  An address CSV with more than 1 % fewer rows than the previous one
  is rejected unless `--force` is given.
- **Exit code** 1 if any input failed,
  except an input marked `optional`, whose failure is only a warning.
  Optional inputs are read by no step:
  the regional constituency announcements,
  records of the sources of the curated regional obvody.

#### The input store

The pinned files are kept in a release of the project's own repository,
`store` in `config/inputs.toml`
(`pbasista/election-map-slovakia`, the pre-release `inputs`):
each file is an asset `<sha256>-<file>` of that one release,
downloaded without a login from
`https://github.com/<repository>/releases/download/inputs/<sha256>-<file>`.
An asset is never replaced; a new pin adds one.
Input file names are therefore limited to `[A-Za-z0-9][A-Za-z0-9._-]*`,
what GitHub allows in asset names.

To take a newer file of an input:

1. `ems inputs update NAME...` downloads each named input from its source
   whatever its pin, checks it as `fetch` does
   (`--force` accepts the drop in address rows),
   and, where its sha256 differs, writes the new `sha256`
   and `retrieved` into `config/inputs.toml`, keeping its comments;
2. `ems inputs publish` uploads, with the GitHub CLI
   (`gh`, logged in as a user who may write to the repository's releases),
   every pinned file the release lacks, from `data/raw/`;
   files already there are left as they are.
   Where the release does not exist yet, it creates it first,
   as a pre-release (a draft is refused: its assets are not public);
3. `ems make`, `ems data lock` ([Keys](#keys)), and commit.

### `candidates`

Reads each election's candidate lists
(`candidates` in `config/elections.toml`, in the `format` it names:
`mvsr` the four MV SR lists, `susr` ŠÚ SR's packages of 2022, or of
one of the elections held apart before (2018 municipal, 2017 regional),
`susr-by` a by-election's package
(of 2019–2022 with the election's `candidates.toml` in place of
some of its contests, where there is one),
`volbysr` ŠÚ SR's candidate tables of a country-wide election,
`curated` the election's `candidates.toml`;
`src/election_map_slovakia/lists.py`)
and the municipality table of ZBGIS
(level 0, unpacked once into `data/build/`),
and writes `data/build/<day>/candidates.json`,
with a summary of counts, merges and incumbents on stdout.
It adds the contests the election's configuration names
without candidacies:
a referendum's questions, a party-list election's party contest
and each party's list.
It runs oldest first: a by-election reads its term's `candidates.json`
(which council obvody its seats lie in).
Its schema is described in `src/election_map_slovakia/candidates.py`,
the incumbent rules in `src/election_map_slovakia/incumbents.py`.

- **Municipalities.**
  Every row of MV SR's lists is matched to a municipality
  by name within its okres,
  giving the 6-digit ŠÚ SR municipality code
  (`BA` and `KE` for the cities of Bratislava and Košice);
  ŠÚ SR's tables and the curated lists give their contests' areas by code.
  Residences of regional candidates are matched within their kraj,
  those of country-wide candidates by name among all obce;
  where no one obec has that name,
  the name as written is kept (`residence_name`).
  Any row that matches nothing makes the command fail
  with a list of all such rows, to be fixed in `config/overrides.toml`.
- **Persons.**
  Candidacies of one person in several contests
  are merged by municipality, name and age
  (a presidential candidate in both rounds is one person).
  The by-election packages of 2019–2022 give no age:
  their candidacies of one name in one obec are merged as one person.
- **Only the elected.**
  The same packages list a council's elected only:
  its contest is marked `elected_only`, which the app says.
- **Uncontested.**
  A contest called but held nowhere, no candidate having registered,
  is a contest without candidacies marked `uncontested`
  with the URL and title of what says so,
  its seats where known:
  - ŠÚ SR's territorial division (`Typ volieb` per municipality:
    `tab0c` of 2018, `tab0dd` of 2022 in the package,
    `tab0dd` of 2026 as the `mvsr` lists' `units`):
    "Nekonajú sa" (no mayor, no council: 5 municipalities in 2018,
    5 in 2022, 3 in 2026) and "Len zastupiteľstvo"
    (no mayor: 6, 7 and 3);
  - a by-election's package: "Nekonajú sa" with the seats called
    (none: the mayor), its council's in the one obvod of its term's
    (of several the obvod is not known: the summary names it,
    Divinka 2022-03-19);
  - the election's `uncontested.toml`: what the inputs do not tell,
    with the document saying so: a council obvod the municipality's
    decision sets but no candidate stood in
    (Ilava 2018 obvod 6; written by the `obvod-rules` ingest,
    [agent-jobs.md](agent-jobs.md#obvod-rules)),
    a mayor a by-election called beside council seats
    (the Speaker's decision, annex 1: 9 by-elections).
  None may have candidacies, and each has a source
  (`src/election_map_slovakia/lists.py`, `config.py` `load_uncontested`).
  `addresses` fails on an uncontested obvod of a municipality of several
  that is not in the election's own rule set of it
  (another vote's standing in, or reused, is not its decision)
  with its seats and that document.
- **Party lists.**
  A party list's candidates must fit their ballot subject
  (its number, the list size it states);
  `build` rejects a party missing from `config/parties.toml`.
- **Current office holders**
  (mayors, municipal councillors, regional presidents and councillors;
  regular elections only)
  are rebuilt from the ŠÚ SR final results the election's `incumbents`
  names: those of the 2022 elections
  and of every municipal by-election since.
  (The step needs `incumbents` for `mvsr` lists.)
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

### `links`

Links the persons of each election
to the same persons standing in every earlier one
(both as their `candidates.json` has them)
and writes `data/build/<day>/links/<earlier slug>.json`,
with counts of linked, overridden and ambiguous persons on stdout.
A person is linked by the rule the incumbents are found with:
the same name (diacritics ignored),
an age that fits the years between the election days,
and the same obec (a Bratislava or Košice district counting as its city)
or regional candidacies in the same kraj
(a country-wide candidate by the obec of residence, where known);
a person fitting several the tie-breaks do not tell apart stays unlinked,
and so does a person of unknown age
(the by-election packages of 2019–2022 give none).
`config/links.toml` corrects the rule per pair of elections
(`link` and `unlink` pairs of candidacies).
The output lists, per later candidacy,
the person's earlier candidacies for the same office
(the same body: `starosta:500011`, `zsk:4`;
the President in either round, `prezident:SK`;
any party's list of `nrsr:SK` or `ep:SK`),
which `results` (the crosswalk's votes then)
and `build` (the "ran last time" mark,
"Candidacies in other elections", research reused) read.
Each election's persons are read and indexed by name once per run
(`links.read`), not once per later election,
and only persons of one name are compared.
The rule and the format are described in `src/election_map_slovakia/links.py`.

### `addresses`

Reads the MV SR address register
and matches its municipality names like `candidates`
(Bratislava and Košice appear as their districts;
unmatched names fail the command and go to `[address]`
in `config/overrides.toml`).
It needs the contests from `candidates`, so that must have run first.
The output schema is described in `src/election_map_slovakia/addresses.py`.

It writes to `data/build/<day>/addr/`:

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
    of the candidate lists' obvody;
    of a by-election, in one of the rule set's obvody,
    which must include the lists');
  - `pending`, where it (or a city district) has several obvody
    and no rule set yet,
    or a by-election elects part of its council
    (an obvod above 1, obvod 1 without its `seats`,
    or obvod 1 of a council its term elected in several obvody)
    and there is no rule set;
  - `none`, without a council election
    (every obec of a country-wide election,
    every obec of a by-election but those electing a council).

An address resolves to the election's contests there:
of a by-election only those held, of a country-wide election
its country-wide contests, everyone's.

Further:

- **Okrsky.**
  Where the okrsky are known by address (those `geo` draws),
  every street and part in `<obec>.json` also says its okrsok
  (`okrsok`, or `okrsky` per number).
  A rule set that leaves an address in no okrsok or in two is reported
  and its municipality written without okrsky.
- **Job input.**
  The addresses of every municipality
  with several council obvody or several okrsky (the election's `units`),
  or whose council a by-election elects only in part,
  also go to `data/build/<day>/obvod-addresses/`,
  the input of the `obvod-rules` and `okrsok-rules` jobs,
  with the council obvod and okrsok of each address as its rules give them
  (so that `geo` does not assign them again).
  Without `units` no okrsky are counted.
- **Points.**
  Addresses without coordinates stay searchable without a point.
  Every point is checked against the municipality polygon (ZBGIS level 0):
  points more than 100 m outside are published without a point,
  and all points outside are listed with their distance
  in `data/build/<day>/addresses-outside.tsv`.
- **Register cache.**
  What depends on the register alone
  (with ZBGIS level 0 and the register's overrides) is the same
  for every election that reads it:
  the reading and sorting, the point checks,
  the search index, the streets and parts of every `<obec>.json`,
  the job input of every municipality, the outliers.
  The first election on a register makes it,
  in `data/build/shared/addresses/<register input>/`,
  keyed on the sha256 of all of it and of the code;
  the others add their council obvody and okrsky
  (15–25 s of each election becomes 0.4–3.5 s; making it takes about 20 s).
  `results` reads the register's rows for its crosswalk from there too.

It prints the counts, the municipalities pending street rules,
the farthest outliers,
a random sample of 100 addresses resolved to their contests,
and the file sizes (raw and gzip).

### `geo`

Reads ZBGIS boundary levels 0–2,
reprojects them from S-JTSK (EPSG:5514) to WGS84,
and writes to `data/build/<day>/geo/`:

- `okres/<okres>/<lod>.json`: the obce of each okres
  at three levels of detail;
- `coarse.json`: a coarse view for the lowest zooms,
  with the kraj, okres and obvod labels
  and the seats of every regional and city council obvod drawn;
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
(`data/curated/elections/<election day>/`, see [Curated data](#curated-data)),
only for what the election's contests need:
`zsk-<kraj>.toml` for a kraj with regional council contests,
`BA.toml`, `KE.toml` for a city with city council contests
(a country-wide election, and most by-elections, need none;
an obec's `zsk` is then 0).
It must cover every obec of its area exactly once,
with as many obvody as the candidate lists have
(of a by-election, at least those with a contest),
so `candidates` must have run first.
A municipality that elects its council
and has a council obvod rule set (`obvody/oz/` there)
is cut into its council obvody
(an election without council contests cuts nothing):

- unions of cadastral areas, where the rules (or its addresses) say so;
- else cut by street blocks, marked approximate:
  the municipality cut by the roads, railways and waterways
  of the election's OpenStreetMap extract (its `osm` input),
  its cadastral borders and its own.
  A settled block whose addresses are all of one obvod goes to it whole;
  a mixed block (a street split by house numbers)
  is cut between its obvody by its address points,
  so that every located address is drawn in its own obvod
  (but where several obvody's addresses share one point);
  in a mixed block, and in a sparse one
  (a forest or field whose houses' 50 m reach covers less than a tenth of it),
  only the land within 50 m of the houses is theirs.
  Empty land (fields, forests, water, the rest of those blocks)
  goes as whole blocks to the obvod it shares the most border with,
  growing from the settled blocks (not from a cottage in a forest), smoothed,
  and address-less fragments to the obvod around them;
  strips narrower than 15 m (a street and the path beside it,
  a dual carriageway) are first cut across where other lines meet them,
  so that they go piece by piece to the land beside them.
  Cottages of a sparse block left as an island in another obvod's land
  keep only their plots (25 m round each house, reaching to its road
  where that is within 50 m); parts of an obvod narrower than 3 m go to
  a neighbour, as they would fold when rounded to the map's grid
  (slivers told by their width, however short).
  The blocks are noded, and the areas within the cut overlaid,
  on one 1 cm grid, keeping to polygons:
  snapped, a tip under a centimetre wide collapses into a line.
  The borders then run along streets, railways, rivers
  and cadastral borders, and between houses in mixed blocks,
  simplified by 2 m along the lines and the plots and 8 m within the blocks,
  without moving an address out of its obvod
  or nearer than 1 m to its border (or than it was).

So `addresses` must have run before `geo`.
The lines are read once per extract and version of the code that reads them
(basemap's, not geo's) into `data/build/shared/barriers/`,
and only when some municipality's cut is not cached.

**Okrsky.**
Where a rule set also gives the okrsky of each obvod and their rules,
`geo` draws the okrsky within the obvody
(unions of cadastral areas where they allow,
else by the street blocks within the obvod, like the obvody);
likewise the okrsky of a municipality with one council obvod
(`okrsky/<obec>.toml`) within the whole municipality.
It cuts them from the municipality's map features
at every level of detail
and writes them per okres, beside the municipalities.
It fails if an address is in no okrsok or in two,
or the okrsky do not tile their obvod or their municipality on the map.

**Shared work.**
Much of `geo` is the same for many elections, made once
in `data/build/shared/geo/` (one directory per version of the code;
each entry keyed on the sha256 of the ZBGIS and Natural Earth inputs
and of all else it depends on):
the obce read, simplified, rounded and labelled
(per set of obce cut by cadastral area: the same for every election
without such cuts),
the countries around Slovakia,
the overlaps and gaps of each level's features,
and each municipality's cut into council obvody and okrsky,
keyed on its rule set (but for the documents, dates and notes,
which only say where the rules come from),
its addresses file and its street block lines:
a rule set reused with the same address register and extract is cut once.
So are the cuts placed in the shards, each municipality's at every level
and the okrsky of each of its obvody, keyed on what they are cut from.
The rest is per election: those cuts bent alike
(per level in worker processes),
the arcs, the files and the checks.

**Checks and summary.**
The command fails if neighbouring areas overlap
or leave gaps after rounding,
or if the countries around leave a gap at Slovakia's border at any level.
It prints the seat totals,
obvody with fewer candidates than seats,
how the obvody and okrsky drawn from addresses look at full detail
(pieces besides each unit's largest, with and without addresses;
addresses drawn outside their own unit, shared points apart;
compactness; border length),
the measured overlap and gap areas, and the file sizes.
`--preview OKRES` also writes SVG previews
of the country, Bratislava and that okres for a visual check,
and of each municipality of it cut by its addresses, with their points.

### `basemap`

Reads the OpenStreetMap extract of Slovakia with pyosmium
and writes the faint base map
that the app draws under the election colours
to `data/build/base/<extract>/base/`,
once per extract, for every election on it
(`--election`: that election's extract only).
It reads the extract, the okresy of ZBGIS level 1 it is cut by
and the obce of level 0 its buildings are filed by,
the same for every election on the extract (`Config.bases`),
and nothing of an election.
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
  It takes about 22 s:
  one worker writes the ways (roads, railways, waterways, buildings)
  with their nodes' locations to a scratch file in `data/build/`,
  while others read the water and multipolygon areas;
  then all the workers read that file, a run of its blocks each,
  simplify the levels, clip them to the okresy,
  place the buildings in their obce
  and encode the files of the obce, a share each
  (gzipping the 81 MiB, for the summary, takes another 1.5 s
  for the files not measured before: see [Gzip sizes](#gzip-sizes)).
  An election of the same extract as another takes that one's output
  (see [Skipping what is up to date](#skipping-what-is-up-to-date)).

### `results`

A step of `make` only.
It writes each election's final results,
`data/build/<day>/results/`,
from the definitive results
pinned as the inputs the election's `results` names,
in its `format`
(`results-oso<year>` and `results-osk<year>` of a regular election;
a by-election's package, `susr-by`;
ŠÚ SR's national tables of a country-wide election, `volbysr`,
a presidential election's per round),
as of their data, so that the same inputs give the same files.
Without them the election has no final results.
Nothing else writes the directory.

`ems results` writes the live results of an election night apart,
`data/build/<day>/live/`:
from volbysr.sk as the votes are counted
(`poll`, municipal and regional elections only)
or as dummy data (`fake`);
they leave this step, its stamp and its record alone.
`results deploy` writes `dist/live/` with them
and deploys it ([results.md](results.md)).
`build` links the final results into `dist/results/<election day>/`
and the live results into `dist/live/<election day>/`,
where the app reads them; each election has its own.
The file format, the sources and the night's steps
are in [results.md](results.md).

### `build`

`build` updates `dist/` in place (renamed `dist.part/` meanwhile):
a file already there with the content wanted stays,
and the files it copies from `data/build/` (the map bundles, the base
maps, the results)
are hard links to them, which no step ever writes into (it replaces them).
Each map bundle's and base map's files are read once, in a worker process,
for its version and the sizes; each data bundle is made in one.
`check` verifies each content once, however many bundles share it,
and keeps what it verified, and the check of each election's results,
in `data/build/shared/check/`
(keyed on the content, the code and the libraries),
so that the next run verifies only what changed.

Writes the site from `web/`,
the outputs of the steps above for every election,
their results (if there) and the configuration;
the same inputs give the same bytes.
It prints file counts and sizes (raw and gzip) per group,
the elections together,
and notes when `data/published.toml` is stale ([Keys](#keys)).
The layout is described in `src/election_map_slovakia/build.py`
and `bundle.py`.

The site is written in parts,
each deployed to a Cloudflare Pages project of its own
(`config/site.toml`; [deploy.md](deploy.md)):

- `dist/app/`: the app (shells, language picker, 404 page, assets,
  UI strings, `_headers`, `sitemap.xml`), project `pages_project`;
- `dist/map/<slug>/`: each election's map bundle, project `map_project`
  (`ems-map-{slug}`);
- `dist/data/<slug>/`: each election's data bundle, project `data_project`
  (`ems-data-{slug}`);
- `dist/base/<extract>/`: the base map of each extract, which every
  election on it shows, all deployed to one project, `base_project`
  (`ems-base`);
- `dist/sources/`: the cached copies of the pages research cites
  (`cache/<sha256>.html`, `assets/cache.css`),
  project `sources_project`, at `sources_url`;
- `dist/results/`: every election's final results, `<day>/`,
  project `results_project`, at `results_url`;
- `dist/live/`: every election's live results, `<day>/`,
  project `live_project`, at `live_url`,
  which only `ems results deploy` deploys, never a release.

Each data part has its own `_headers` (from `web/_headers-<part>`:
cross-origin reads allowed),
a `404.html` (`web/part-404.html`)
and a `manifest.json` with its key
(the live part, which has none, with the version of each election's);
a bundle's and a base map's manifest also list its version and its files
(a base map's version of its files alone, so that a change of an
election's map leaves it as it is),
a data bundle's also, per language, the occupations still untranslated.
The app's shells name, in their `km-config`,
where the election's bundles, base map, results, live results (with
`live`) and cached copies are:
`/map/<slug>`, `/data/<slug>`, `/base/<extract>`, `/results/<day>`,
`/live/<day>` and the root when built plainly,
the deployed origins with `--deployed`;
a shell whose map bundle or base map is on another origin preconnects to
it.
The app's CSP lets it fetch from its own origin
and those of the bundles, base maps and results,
and of the live results where an election reads them.

An election's files are split in two bundles by what they depend on
([Keys](#keys)):
its map bundle holds
the geometry (`geo/`) and address files (`addr/`),
which depend on that election alone,
and its base map is its extract's;
its data bundle holds
the occupations of its candidates translated
(`i18n/<lang>.json`, every language but Slovak),
and in `data/`

- the candidates, split so that a place needs at most three small files:
  municipal contests per okres,
  Bratislava and Košice city contests,
  regional contests per kraj;
  the country-wide contests in `country.json`
  (the president's rounds, a referendum's questions,
  the parties of a party-list election)
  and each party's list in `list/<p>.json`, loaded when opened.
  A candidate linked to a person of another election
  (`data/build/<day>/links/`) comes with every candidacy of that person
  there and, where that election's results are final,
  how it went: votes, valid ballots, rank by votes among the contest's
  candidates, and elected or not
  (the app's "ran last time" mark and the card's list of other elections);
- the research summaries and findings
  (`research/<lang>/`, per area file as the candidates):
  the election's own where its candidates were researched
  (the latest's, the presidential elections'),
  and for any other election, for each person linked to a researched one
  of the latest, that research cut to the findings whose source was
  published before that election's day;
  undated findings are left out and counted;
- a candidate-name search index, sharded by two-letter prefix;
- the About dialog's sources and decisions (`about.json`):
  the inputs the election names and those no election names,
  and for an election other than the latest what it takes from the latest
  and what it lacks, with counts (`substitutes`),
  and the municipalities whose units another vote's stand in for,
  by that vote's day (`stand_ins`; the app names the vote);
- in `index.json`, besides the names and the parties
  (of the candidacies and of a party-list ballot),
  where a by-election is held (`held`: obec or kraj → its contests),
  and what the ballots and the map
  say of an obec whose units are not the election's own:
  council obvody drawn with another election's rules (`reused`),
  or with another vote's standing in, earlier or later, though the layout
  is not proven to match (`adopted`, `okrsky_adopted`; `ems job reuse`),
  not drawn for want of a document (`not_found`),
  okrsky of another election or a referendum,
  obvody or okrsky from a document dated only approximately
  (`date_approximate`, `okrsky_date_approximate`),
  or partly from a later source where the document does not place
  every address (`supplemented`, `okrsky_supplemented`),
  okrsky not drawn though it voted in several (`okrsky_unknown`),
  and a boundary that moved since (`boundaries`, from `boundaries.toml`).
  The shells of an election drawn on a later election's boundaries
  (not the newest of its `zbgis` inputs)
  name the dates of its base map and
  addresses (`as_of` of their inputs in `inputs.toml`, required there)
  and the later boundaries it is drawn on, for the map's credits.

The app, shared by the elections, holds

- the UI strings per language;
- an app shell per language and election under `/<lang>/<slug>/`,
  the home election's also under `/<lang>/`,
  the page both name as canonical;
  its title, description and noscript paragraph are those of
  the election's kind
  (`app.title.<kind>`, `app.description.<kind>`, `app.features.<kind>`),
  the home election's, the site's front page, after the site's own
  (`site.description`, `site.features`), as are the root page's;
- `sitemap.xml` of the canonical pages;
- a root page that picks the language:
  the stored choice, the browser languages
  with the aliases from `config/languages.toml`,
  then the first fallback.

**`--deployed`.**
Builds the app alone, for the data parts deployed with the keys
of `data/published.toml`:
it finds through the Pages API
(with the login of `npx wrangler login`,
or `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` where set)
the production deployment of each bundle's project
that carries the bundle's key,
reads its `manifest.json` there,
and writes `dist/app/`
and, for `check`, each `dist/map/<slug>/manifest.json`
and `dist/data/<slug>/manifest.json` alone.
It needs nothing of `data/build/`.

**Versioned paths.**
The code goes to `/assets/<v>/`,
the vendored libraries to `/assets/vendor/<vv>/`
and the images to `/assets/img/<iv>/`,
each version a hash of its files.
The app fetches its election's files with `?v=` the version
of their bundle's or base map's manifest, the map's, the data's or the
base map's (the same for every election on the extract),
and the UI strings with `?v=<strings version>`, a hash of them alone,
the same on every election's page.
So a release replaces browsers' copies of what changed
and keeps the rest
(see "Cache busting" in the module doc,
and [Caching in deploy.md](deploy.md#caching)).

### `serve`

Serves the parts of `dist/` as one site
with Python's HTTP server for local testing
(`--host`, `--port`; default <http://127.0.0.1:8000/>):
the app at `/`, each bundle at `/map/<slug>/` or `/data/<slug>/`,
each base map at `/base/<extract>/`, the final results at `/results/`,
the live results at `/live/`,
and the cached copies at the root, where the app has no such path.
Each part's responses carry the headers of its own `_headers`,
read once at startup,
and a missing path is answered with the part's `404.html`
and status 404,
as Cloudflare Pages does
(without a `404.html`, Pages would answer them
with the root page and status 200).

### `check`

Verifies `dist/`, part by part, and prints a table of its checks.
It lists the problems, by their path in `dist/`
(`map/2026/geo/…`, `app/i18n/cs.json`),
and exits with 1 if there are any.
The checks are described in `src/election_map_slovakia/check.py`:

- **Budgets:** at most `file_budget` files in each part
  (each is a Pages project of its own)
  and no file above `max_file_bytes` (`config/site.toml`;
  Cloudflare Pages allows 20,000 files and 25 MiB per file;
  each base map is a deployment of its own, with its own budget).
- **Formats:** valid JSON; each part's `_headers` within the Pages limits;
  every data part with its `404.html` and `manifest.json`,
  a bundle's or base map's manifest listing exactly its files.
- **Completeness:** every file the frontend can request is present,
  where `serve` maps it:
  assets, shells and UI strings of every language and election,
  and for every election
  its geometry shards and polling district files,
  the base map files of its extract's `index.json` (`base/<extract>/`),
  the address file of every municipality, name shards,
  and the candidate files: of a regular election every municipality's,
  of the others the area file of every contest.
  An app built with `--deployed` is checked
  against the files the deployed bundles' and base maps' manifests list;
  their content was checked where they were built.
- **Contests:** every contest of every election
  in exactly the area file the frontend looks in
  (`contests.area_name`, kinds.js `areaName`).
- **Councils:** every council contest of a by-election
  in a municipality whose council its term
  (the regular election before it) elected in several obvody
  has the municipality's addresses placed in them by a rule set
  (`by_address` of its data index;
  `ems job reuse` copies the term's, see
  [agent-jobs.md](agent-jobs.md#an-earlier-election)):
  without, the map and the address lookup
  take the contest for the whole municipality's;
  and one numbered above its term's council contests
  is an obvod of the term's rule set
  (its decision; one without candidates is uncontested there).
- **Origin:** no HTML, JS or CSS of the app refers to another origin
  except as a link target or the data parts' origins its shells name,
  and the CSP's connect-src is `'self'`
  and the origins of the bundles, base maps and results.
- **Results:** the results of every election day in `results/`
  keep their format, have the sources of exactly
  that election's contests
  and list exactly their files with their hashes
  ([results.md](results.md#the-votes-add-up)).
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
- **Base map:** each has the levels of detail and okresy of the shards
  of every election on its extract,
  holds no file its index does not let the app request,
  and each file only the line classes of its level.

## Keys

Each data part has a key, 16 hex digits,
computed from the repository alone, without building
(`src/election_map_slovakia/lock.py`).
An election's map bundle is keyed by that election alone:
the inputs of `candidates`, `geo` and `addresses`
with their pins (the extract among them: `geo` reads its roads),
what those steps read of its `elections.toml` table and of `overrides.toml`,
its curated data (`data/curated/elections/<day>/`),
the code of those steps and its libraries' versions,
and the part's own web files.
A base map is keyed by its extract and ZBGIS levels 0 and 1 with their
pins, the code of `basemap` and its libraries' versions,
and the part's own web files: nothing of an election,
so the elections on one extract share its key.
The data bundles and the results are keyed by
the code that makes the data and its libraries' versions,
the elections' configuration (but `live`),
every input's configuration with its pin,
the rest of `config/` but `site.toml`,
the curated elections,
and the part's own web files;
the data bundles' also by the research and its translations,
which the results never read.
The elections are entwined
(links, reused research, results compared with the election before),
so a change to any election's candidates, results or curated data
changes every data bundle's key;
research, links and translations change no map key nor base map key,
and research and translations no results key either,
so that a release of them does not deploy the same results again,
and a new pin of an extract changes the keys of its base map and of the
maps of the elections on it alone.
Code counts by its source text, comments included,
so that every Python computes the same keys.
Changes to the app alone (`web/`, UI strings, `site.toml`)
change no key.

`ems data lock` writes the keys to `data/published.toml`
(`sources`, `results`, `[map] <slug> = key`, `[data] <slug> = key`,
`[base] <extract> = key`),
which is committed with every change to them;
`ems data lock --check`, run by CI, fails when it is stale.
Every input must be pinned for the keys to exist.
`ems data status [--github-output]` says which parts
are not deployed with their locked key,
and `ems data deploy` deploys those from `dist/`,
each carrying its key;
a release runs them ([deploy.md](deploy.md)).

## Identifiers

| Identifier | Form | Examples |
|---|---|---|
| obec | the 6-digit ŠÚ SR municipality code (ZBGIS `IDN4`), or `BA` and `KE` for the cities of Bratislava and Košice | `528595` (Bratislava-Staré Mesto) |
| okres | ZBGIS `IDN3` (the candidate lists' `Kód okresu`) | `806` |
| kraj | ZBGIS `IDN2`, 1–8 | `8` |
| contest | `<kind>:<area>[/<sub>]` (`src/election_map_slovakia/contests.py`): `starosta` (mayor) and `oz` (municipal council, sub its obvod) of an obec; `predseda` (regional president) and `zsk` (regional council, sub its obvod) of a kraj; of the whole country, area `SK`: `prezident` (sub the round, 1 or 2), `referendum` (sub the question), `nrsr` and `ep` (the party contest, its candidates the parties by ballot number; sub a party's number: that party's list). The id without `/<sub>` is the body, the office elected | `starosta:508438`, `oz:528595/2`, `predseda:8`, `zsk:7/2`, `prezident:SK/1`, `referendum:SK/2`, `nrsr:SK`, `nrsr:SK/12` |
| candidacy | `<contest>#<ballot number>` (a party's number in a party contest, the position on a party's list); stable, and the key of the election results | `oz:528595/2#7`, `nrsr:SK/12#3` |
| person | a short hash of the obec, name and age that merge candidacies (`merge_persons` in `src/election_map_slovakia/candidates.py`), corrected in `config/overrides.toml` | `9a9a5bf4bc1d` |

## Configuration

| File | What it holds |
|---|---|
| `config/site.toml` | The site's own domain (`base_url`, empty until it has one), source repository, the Cloudflare Pages projects of the parts and the addresses of the sources, the final results and the live results, output budgets |
| `config/elections.toml` | The elections the site shows, by slug: kind, day, the polls' hours, whether the app reads the live results (`live`) and for how many days after the polls close (`live_days`; at any time in a build with `EMS_RESULTS_ANYTIME=1` in the environment), what only its kind has, and the inputs each step reads ([Elections](#elections)) |
| `config/languages.toml` | UI languages with the site's name in each, fallback chain, browser aliases |
| `config/sources.toml` | Allowlist of sources for research, by category; the reports the media were selected from; which categories each research language searches |
| `config/municipal-domains.toml` | Official websites of municipalities and regions, which research may cite (category `official`) |
| `config/blocklist-konspiratori.txt` | Dated snapshot of konspiratori.sk |
| `config/inputs.toml` | Official input files, their URLs, checks and pins (`sha256`, `retrieved`), and the input store (`store`) |
| `config/certs/` | Intermediate CA certificates some input servers omit |
| `config/overrides.toml` | Municipality-name fixes (candidate lists and address register) and person-merge corrections |
| `config/parties.toml` | Every party and ballot subject of the candidate lists: short form, official name (Ministry of Interior register), a coalition's `members` (which set its threshold), and per election the logo it used then, a file in `web/img/parties/` with its source and licence; `build` rejects candidacies and ballot subjects of parties missing here |
| `config/links.toml` | Corrections to the links between the persons of two elections ([`links`](#links)): `link` and `unlink` pairs of candidacies, per pair of elections |

## Curated data

Hand-curated inputs, committed:

- `data/curated/elections/<election day>/`:
  what the state sets anew for each election,
  kept per election (`day` in `config/elections.toml`),
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
  - `candidates.toml`: the candidate lists transcribed by hand,
    for an election whose `candidates` format is `curated`
    ([elections.md](elections.md#the-curated-format)).
  - `boundaries.toml`, for an election drawn on a later election's
    ZBGIS boundaries (the same `zbgis` inputs):
    the date its own boundaries are of (`compared`)
    and each obec whose land moved since by more than redrawing
    (`[[change]]`, `state_border` where along the state border);
    the ballots, the map's credits and About say so.
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
- `data/published.toml`:
  the keys of the data parts ([Keys](#keys)).
