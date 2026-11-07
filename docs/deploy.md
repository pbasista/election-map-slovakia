# Releases and deployment

The site is hosted on Cloudflare Pages
and deployed from GitHub Actions;
both fit their free plans.
A push runs the checks; a version tag deploys what changed.

The site is deployed in parts, each a Pages project of its own,
so that a release deploys only what it changes:
the app changes with nearly every release,
an election's data seldom once its inputs are pinned,
its map and the base map more seldom still.

| Part | Built in | Pages project (`config/site.toml`) | Served at |
|---|---|---|---|
| the app: page shells, code, styles, UI strings | `dist/app/` | `pages_project`, `election-map-slovakia` | `volebnamapa.sk` |
| an election's map bundle: geometry, addresses | `dist/map/<slug>/` | `map_project`, `ems-map-<slug>` | the address of the deployment that carries its key |
| an election's data bundle: candidates, research, occupations, About | `dist/data/<slug>/` | `data_project`, `ems-data-<slug>` | the address of the deployment that carries its key |
| the base map of an OpenStreetMap extract, which every election on it shows | `dist/base/<extract>/` | `base_project`, `ems-base` (one for every extract) | the address of the deployment that carries its key |
| the cached copies of the pages research cites | `dist/sources/` | `sources_project`, `ems-sources` | `sources_url`, `sources.volebnamapa.sk` |
| the final results of every election | `dist/results/` | `results_project`, `ems-results` | `results_url`, `results.volebnamapa.sk` |
| the live results of an election night, which only `ems results deploy` deploys, never a release | `dist/live/` | `live_project`, `ems-live` | `live_url`, `live.volebnamapa.sk` |

How each is laid out is described in `src/election_map_slovakia/build.py`
(the app) and `bundle.py` (the data parts).
Each part has its own `_headers` and `404.html`,
so its file budget (20,000 files on the Free plan) is its own too:
a base map is one deployment of `ems-base`, its budget its own.

## Keys and the lock

Every data part has a key:
a digest of everything in the repository its content depends on,
computed without building anything (`src/election_map_slovakia/lock.py`).

- **What counts:**
  - the pinned inputs (`config/inputs.toml`);
  - what the steps read of `config/elections.toml`
    (not the polls' hours nor `live`, which only the app reads);
  - the other configuration files but `site.toml`;
  - the curated data and their translations;
  - the source of the code that makes the data, comments included,
    and the versions in `uv.lock` of the libraries it runs on;
  - the part's own files of `web/` (`_headers-<part>`, `part-404.html`).
- **What does not:** the app's code, styles and UI strings,
  the site's configuration and the package version.
  A release that changes only those builds and deploys the app alone.
- **An election's map**
  depends on that election alone:
  its candidate lists (the contests shape the map),
  boundaries, address register, territorial division
  and the OpenStreetMap extract
  whose roads, railways and rivers `geo` cuts by,
  its curated obvody and okrsky,
  and the code of the steps that make the map.
  Research, links between persons, translations, party logos, results
  and the other election's data do not reach it.
- **A base map**
  depends on its extract alone:
  the extract, the ZBGIS okresy it is cut by and obce its buildings
  are filed by (levels 1 and 0, the same for every election on it,
  which `config/elections.toml` must keep so),
  and the code of `basemap`.
  The elections on one extract share it, one key and one deployment;
  a change to an election's map leaves it as it is.
  Its extract and ZBGIS inputs are the map's too,
  so a new pin of them changes both.
- **Entwined elections:**
  each election's persons are linked to those of every other,
  with their candidacies and results there;
  the research of the latest election's candidates is reused
  for the other elections;
  an election's results are compared with those of the election
  of its kind before.
  So a change to any election's candidates, results or curated data
  changes every data bundle's key;
  only an election's own records of sources change its data bundle alone.
  A new research finding changes the data bundles and no map.

The keys are locked in `data/published.toml`,
committed like `uv.lock`:

```sh
uv run ems data lock           # write the keys
uv run ems data lock --check   # fail if they are not those of the repository
```

`ci.yml` runs the check on every push,
so a commit that changes data without the lock fails:
a stale lock would make a release take changed data for deployed.
`ems build` says when the lock is not that of the data it built.
Every input must be pinned for the keys to exist;
`ems inputs update` pins one (below).

A data deployment carries its key as its commit message:

- **A bundle**, map or data, **or a base map** is deployed once per key.
  The app names it by the address of that deployment,
  `https://<id>.ems-map-<slug>.pages.dev`,
  `https://<id>.ems-data-<slug>.pages.dev`
  or `https://<id>.ems-base.pages.dev`,
  which keeps serving that deployment's files
  whatever is deployed after it,
  so a part never changes under a page that uses it,
  and its files may be kept for good (`web/_headers-data`).
  The elections on one extract name the same base map deployment
  with the same version (`?v=`),
  so a browser that has its files keeps them from one election to another.
  The page connects to the map's and the base map's servers as it loads
  (a preconnect in the shell),
  so their other addresses cost it no extra round trip.
- **The sources and the results** are served at their domains
  by their project's current production deployment,
  which is deployed anew when it carries another key.

`ems data status` says which parts are not deployed with their key,
`ems data deploy` deploys those of `dist/`
to projects `ems data projects` creates beforehand
(see `src/election_map_slovakia/pages.py`).

## What runs when

| Event | Workflow | What it does |
|---|---|---|
| push to any branch, pull request from a fork | `ci.yml` | Ruff, ty, pytest, `ems data lock --check` and `ems record check` on Python 3.11, 3.12, 3.14 and 3.15; Biome on `web/`. Nothing is downloaded or built. |
| push of a tag `vX.Y.Z` | `release.yml` | the checks of `ci.yml`; then what changed is built and deployed |

`release.yml` runs these jobs:

1. **ci**: the checks above.
2. **plan**:
   checks that the tag matches `__version__`
   in `src/election_map_slovakia/__init__.py`,
   and asks the Pages API which data parts are not deployed
   with their key in `data/published.toml`
   (`ems data status --github-output`,
   which also writes the days of every election for the steps job
   and the extracts of the base maps for the basemaps job).
3. **inputs**, only if any data part is not deployed:
   downloads the pinned inputs (`ems fetch`, about 3.3 GB)
   from the input store into the Actions cache,
   keyed by `config/inputs.toml`.
   A cache belongs to the tag it was saved for
   ([GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)):
   it carries the inputs to the jobs below and to re-runs of the release,
   and the next release downloads them again.
4. **candidates**:
   takes the inputs from the cache,
   runs `ems candidates` for every election, oldest first,
   and keeps each `candidates.json` with its stamp
   as one artifact for a day (a zstd tar).
   Once for all the steps jobs, which wait for it:
   a by-election's candidates and addresses read
   the candidates of its term (the regular election
   whose council's seats it fills),
   and many by-elections share a term.
   `tests/test_release.py` fails where a step of the steps job
   reads an output that no job before it makes.
5. **steps**, one job per election, at most 10 at a time:
   takes the inputs from the cache
   and the candidates of every election from the candidates job,
   runs the steps that read no other election's output but those
   (`ems addresses` and `geo` with `--election`)
   and keeps the election's output with its stamps
   as an artifact for a day
   (a zstd tar of `data/build/<day>/`, its candidates among it).
   Every election, not only those of the parts not deployed:
   each data bundle reads every election's candidates and results
   and its own election's `geo`,
   and nearly any change to the data changes every data bundle's key
   ([above](#keys-and-the-lock)).
   Each job makes again what one build shares between elections
   (`data/build/shared/`), costing CPU time but no wall time.
6. **basemaps**, one job per extract, beside the candidates and steps jobs:
   takes the inputs from the cache,
   makes the extract's base map once for every election on it
   (`ems basemap --election` of the first election on it)
   and keeps it with its stamp as an artifact for a day
   (a zstd tar of `data/build/base/<extract>/`).
7. **site**:
   takes the inputs from the cache
   and unpacks the output of every steps and basemaps job;
   `ems make` finds those steps up to date,
   runs `links` and `results`,
   builds and checks the whole site;
   compares the output of every step with `data/outputs.toml`
   as committed (`ems record compare --github`);
   then each data part whose key is not deployed yet is deployed
   (`ems data deploy`).
   Data that do not pass `check` are never deployed.

   An output that is not the one recorded is a warning
   (an annotation, and a table in the job's summary), not a failure:
   the runner is x86-64, the record is written where `ems make` ran,
   mostly aarch64, and output alike byte for byte on both
   is not verified.
   The deployed parts are keyed by the repository, not by the record
   ([above](#keys-and-the-lock)),
   so a difference only means that the record does not let
   a machine like the runner skip the step
   ([pipeline.md](pipeline.md#the-output-record)).
8. **app**, after the site job or, where no data part changed, without it:
   - builds the app for the deployed data parts
     (`ems build --deployed`):
     each election's bundles and base map are the deployments that carry
     their keys, whose `manifest.json` gives each one's version and files;
   - checks it, against those files (`ems check`);
   - deploys `dist/app/` to `pages_project`
     as a production deployment of the branch `main`.
9. **github-release**: creates the GitHub release of the tag
   with generated notes and the app's files attached
   (`election-map-slovakia-X.Y.Z.tar.gz`).

A release that changes no data
skips inputs, candidates, steps, basemaps and site
and takes a few minutes.
A failed job can be re-run from the run's page:
a re-run of the site job deploys only the parts
that the failed run did not deploy;
anything that needs a code change is a new version.

### Timeouts

A job on a GitHub-hosted runner stops after its `timeout-minutes`,
360 by default and at most
([GitHub](https://docs.github.com/en/actions/reference/limits)).
Each job of the release has its own,
about twice or more what it is expected to take
when every data part is stale:

| Job | Timeout (min) | Expected (min) |
|---|---|---|
| ci, test (each Python) | 60 | well under that |
| plan | 10 | 1–2 |
| inputs | 30 | 5–10 |
| candidates | 15 | 2–4 |
| steps (each election) | 45 | 8–15 |
| basemaps (each extract) | 30 | 3–6 |
| site | 120 | 30–60 |
| app | 30 | about 5 |
| github-release | 10 | under 1 |

The estimates scale times measured on 8 CPUs (Apple M1, 4 fast, 4 slow)
by 2 to 2.5 for `ubuntu-latest`,
4 CPUs and 16 GB for a public repository
([GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)):

- `ems make` of 25 elections from nothing took 32 minutes
  (2 CPU hours: `geo` 18½ min, `basemap` 7, `results` 3, `addresses` 1½,
  `check` 1½), 65–80 on a runner;
  one job doing it all, with the downloads and uploads,
  would take some 85–130 minutes.
- `ems candidates` of the 25 elections from nothing took 11 seconds;
  the candidates job mostly restores the inputs from the cache.
- One election's steps from nothing took 3¼ minutes for the largest,
  the municipal and regional elections of 2026
  (`geo` 2¾ min, `addresses` 30 s), and the base map of its extract 46 s;
  the base maps of all 10 extracts took 5 minutes.
- The site job's `make` after the steps took 8 minutes
  (`results` 3½, `build` 2½, `check` 1½).
- Its uploads, with every part stale,
  are some 166,000 files and 2.9 GB in 52 Wrangler runs,
  each uploading at most three batches of 2,000 files or 40 MiB at once;
  15–40 minutes is an estimate, never measured from a runner.

## Releasing

```sh
# set __version__ in src/election_map_slovakia/__init__.py, add the
# version's section to CHANGELOG.md; after a change to the data, also
uv run ems make
uv run ems data lock
# commit (with data/published.toml and data/outputs.toml), then:
git tag v0.1.0
git push origin main v0.1.0
```

## The input store

Every input of `config/inputs.toml` is pinned by its sha256,
and the pinned files are kept in the input store:
the pre-release `inputs` of the project's own repository
(`store` in `config/inputs.toml`).
Each file is an asset named `<sha256>-<file>`, uploaded once
and never replaced,
so every commit that pins one can still be built,
whatever its source serves now or whether it still serves it
(until `--prune`, below, deletes it).
An input's name is not in its asset's name:
renaming an input leaves the store as it is.
`ems fetch` takes a pinned file from `data/raw/` where it is there,
else from the store (no login needed),
else from its source; the digest is checked either way.

When a source publishes a new version of an input:

```sh
uv run ems inputs update addresses-2026   # download, check, write the new pin
uv run ems inputs publish                 # upload the files the store lacks
uv run ems make                           # build with it
uv run ems data lock                      # the keys it changes
git commit config/inputs.toml data/published.toml
```

`ems inputs publish` uses the GitHub CLI (`gh`),
logged in as a user who may write to the repository's releases.
It uploads nothing twice and replaces nothing.
With `--prune` it then deletes the assets no build needs any more:
those that `config/inputs.toml` pins
neither now nor at `HEAD` nor at any version tag (`v*`),
so that every release can still be built again,
but not the commits between them that pinned another version.
`--dry-run` lists what it would upload and delete, changing nothing:

```sh
uv run ems inputs publish --prune --dry-run   # see what would go
uv run ems inputs publish --prune
```

The tag `inputs` is no version (`v*`), so it deploys nothing,
and as a pre-release it never shows as the latest release.
A version's release notes start from the version before it,
not from `inputs` (`release.yml`).

## Setup, once

1. **GitHub.**
   A public repository:
   the About dialog links to it, and it is where mistakes are reported.
   Actions minutes are free for public repositories,
   and the `production` environment the app job reports to
   is available on every plan for them.
2. **The input store.**
   Filled once, with the release created on the way:

   ```sh
   uv run ems fetch
   uv run ems inputs publish
   ```

   `ems inputs publish` creates the release `inputs` where there is none:
   a pre-release, so that it never shows as the latest;
   published, not a draft, so that anyone may download its assets.
3. **API token.**
   Cloudflare dashboard › My Profile › API Tokens › Create Token ›
   Custom token, permission *Account › Cloudflare Pages › Edit*.
4. **Secrets**, of the repository
   (Settings › Secrets and variables › Actions)
   or of its environment `production`
   (Settings › Environments › production),
   which the release jobs that read them name:
   `CLOUDFLARE_API_TOKEN` (the token)
   and `CLOUDFLARE_ACCOUNT_ID`
   (shown on the account's Workers & Pages overview).
   Locally, `ems build --deployed`, `ems data projects`, `ems data status`,
   `ems data deploy`, `ems results deploy` and `scripts/pages_trial.py`
   read the same two variables where they are set,
   and otherwise use the login of `npx wrangler login`
   (`src/election_map_slovakia/pages.py` `credentials`):
   its token, which Wrangler renews when it expires,
   and the one account it reaches.
   A login that reaches several accounts
   needs `CLOUDFLARE_ACCOUNT_ID` set to the site's.
5. **A trial.**
   `scripts/pages_trial.py` creates a throwaway Pages project,
   deploys to it twice and checks what the parts rely on:
   that the API lists each deployment with the key it carries,
   that the first deployment's address still serves its files,
   that the headers of `_headers` and the status 404 reach the browser;
   then deletes the project:

   ```sh
   npx wrangler login     # once, or set the two variables instead
   uv run python scripts/pages_trial.py
   ```

6. **Pages projects**, one per part (one for all the base maps),
   all for direct uploads with the production branch `main`,
   the branch every deployment is made as.
   `ems data projects` lists those the site needs
   (`config/site.toml`, every election of `config/elections.toml`)
   and says which the account lacks, changing nothing;
   with `--create` it creates those, with Wrangler,
   and leaves the existing ones as they are:

   ```sh
   uv run ems data projects            # which exist, which are missing
   uv run ems data projects --create   # create the missing ones
   uv run ems data projects --prune    # delete those no release needs
   ```

   Each is what
   `npx wrangler pages project create <name> --production-branch=main`
   makes, or the dashboard's
   Workers & Pages › Create › Pages › Upload assets.
   A new election, of any kind, adds `ems-map-<slug>` and `ems-data-<slug>`
   ([elections.md](elections.md)), created before the release that adds it:
   `ems data deploy` deploys to them and does not create them,
   so run `ems data projects --create`
   before every release with new elections.
   A new extract adds no project: every base map is deployed to
   `ems-base`.
   If a name's `pages.dev` host is taken,
   Pages adds a suffix to it; the project keeps its name.
   The command also lists, as steps by hand,
   a project whose production branch is not `main`
   and the custom domains of the next section a project lacks:
   it adds none, since a domain needs its zone on Cloudflare first
   and the Pages token may not edit DNS.
   It lists, too, the projects named like an election's bundles
   (`ems-map-<slug>`, `ems-data-<slug>`) of an election
   `config/elections.toml` no longer has:
   those of an election a version tag still lists are kept,
   as an app rolled back to that release names their deployments
   ([Rollback](#rollback));
   `--prune` deletes the others, with their deployments
   (`npx wrangler pages project delete <name> --yes`).
   The app's project, the base maps', the sources' and the results'
   and any project not named like a bundle's are never deleted.
7. **Domains** (below).

The first release deploys every data part, none of whose keys is deployed,
and then the app.

## The domain

The site's domain is `volebnamapa.sk` (`base_url` in `config/site.toml`).

- Every page names its address there as canonical,
  and the language links are absolute.
- The app's `_headers` answers on `<project>.pages.dev`
  and every `<hash>.<project>.pages.dev`
  with `X-Robots-Tag: noindex`,
  so search engines list the site only under its domain.
  Those addresses keep working.
  The data parts are `noindex` everywhere.
- `sitemap.xml` lists the root page and every language's page
  of every election (by its canonical address) under the domain:
  submit `https://volebnamapa.sk/sitemap.xml` to Google Search Console,
  Bing Webmaster Tools and Seznam Webmaster.

Setup, once, after the Pages projects exist:

1. **DNS on Cloudflare.**
   A Pages project can serve an apex domain
   only from a zone on Cloudflare:
   add `volebnamapa.sk` to the Cloudflare account (the Free plan does)
   and change its name servers at the registrar
   to the two that Cloudflare names.
2. **Custom domains.**
   In each project: Custom domains › Set up a custom domain:
   - `election-map-slovakia`: `volebnamapa.sk`,
     and `www.volebnamapa.sk`,
     so that the address people type out of habit works too;
   - `ems-sources`: `sources.volebnamapa.sk` (`sources_url`);
   - `ems-results`: `results.volebnamapa.sk` (`results_url`);
   - `ems-live`: `live.volebnamapa.sk` (`live_url`),
     before the first election night with `live`.

   With the zone on Cloudflare the DNS records are created automatically.
   The bundles need no domain.
3. **One address.**
   In the zone, a redirect rule (Rules › Redirect Rules)
   from `www.volebnamapa.sk` to `https://volebnamapa.sk`,
   keeping the path and query, so that the site has one address.
   To send the visitors of `<project>.pages.dev` there as well,
   add a Bulk Redirect from it.

Moving to another domain later is a new `base_url` and a new release;
the sources and the results move with new `sources_url`, `results_url`
and `live_url`, which change no key.

## Results

The final results of the elections are a part of their own,
`results/<election day>/` ([results.md](results.md)),
which the app reads from `results_url`,
and which the CSP's `connect-src` lets it.
`ems make` writes them from their pinned inputs, and only it,
and a release deploys them with their key.
An election whose definitive packages are not pinned yet has none.

The live results of an election night are another part,
`live/<election day>/`, with no key,
in a project of their own (`live_project`, at `live_url`).
On the night they change every few minutes:
`ems results poll --deploy` (or `ems results deploy` by hand)
writes the live part locally, checks it
and deploys it to `live_project`, without a release
([the night's steps](results.md#a-future-election-night)).
A release never deploys the live part
and the night's commands never touch the final results,
so a release on the night, whatever it changes,
leaves the live results as they are;
the app reads them where an election has no final results yet.
The release that pins the final results deploys them,
and the app switches to them.

### Live results: `live`

Whether the app reads the live results
is switched per election by `live` in `config/elections.toml`.

- **On:** the app reads the results only from the polls' closing
  (`polls_close`), every minute while the page is in view,
  for `live_days` (7) days:
  the final results' `status.json`, and where there is none yet
  the live results' (`live` and `liveWindow` in the shells' config).
  Before that it reads nothing, after that the final results
  once per page load,
  so that a page left open, or an old copy of the site in a cache,
  stops polling while the final results stay shown.
- **Off** (as once the final results are in a release):
  it reads the final results alone, once per page load, at any time;
  the CSP names no live origin.
- **`EMS_RESULTS_ANYTIME=1`:** a build with it reads the live results
  of every election at any time, every minute, for testing,
  whatever `live`.

Turn it on for the next election before its night,
off again in the release with its final results;
both are releases of the app alone.

## Caching

Pages serves HTML with `max-age=0, must-revalidate`,
so every page load sees the current release.

- **The app:** code, libraries and images live under versioned directories
  that browsers keep for good;
  the UI strings are fetched with `?v=` a hash of them and kept a day
  (`web/_headers`).
- **A bundle or a base map:** fetched with `?v=` its version
  (a hash of its files, in its `manifest.json`)
  from an address that always serves the same files,
  so kept for good (`web/_headers-data`).
  A base map's version is of its own files alone,
  so a new map of an election leaves the base map's URLs as they were,
  and every election on its extract asks for the same URLs.
- **The results**, final and live: `status.json` revalidated on every
  load, every other file fetched with `?v=` its hash and kept a day
  (`web/_headers-results`, `web/_headers-live`;
  [frontend.md](frontend.md#results-and-caching)).

A release keeps the versions, and so the browsers' copies,
of whatever it does not change:
a code change leaves the libraries, the images and the data cached;
a library upgrade is new code too,
since the code names the libraries' directory;
new images are a new app, the data name the logos by file only.

## Rollback

Each project keeps its deployments.
Rolling the app back in the dashboard
(Workers & Pages › election-map-slovakia › Deployments › Rollback)
brings back the data it was built with,
since it names each bundle and base map by its deployment.
The sources and the results roll back on their own projects;
the next release deploys them again
if their current deployment does not carry the locked key.
The live results roll back on theirs, which no release deploys.

## By hand

The same build locally, then a look at the result:

```sh
uv run ems fetch
uv run ems make
uv run ems serve
```

`ems serve` serves the parts as one site,
where an app built without `--deployed` finds them:
each bundle at `/map/<slug>/` or `/data/<slug>/`,
each base map at `/base/<extract>/`, the final results at `/results/`,
the live results at `/live/`, the cached copies at `/cache/`.

Deploying by hand, with the API token and account in the environment
(or after `npx wrangler login`, for Wrangler alone):

```sh
uv run ems data projects --create   # the projects of new elections
uv run ems data status              # what is not deployed
uv run ems data deploy              # the data parts of dist/ not deployed
uv run ems build --deployed         # the app for them
uv run ems check
npx wrangler pages deploy dist/app --project-name=election-map-slovakia --branch=main
```
