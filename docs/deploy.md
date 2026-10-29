# Releases and deployment

The site is hosted on Cloudflare Pages
and deployed from GitHub Actions;
both fit their free plans.
A push runs the checks; a version tag deploys what changed.

The site is deployed in parts, each a Pages project of its own,
so that a release deploys only what it changes:
the app changes with nearly every release,
an election's data seldom once its inputs are pinned,
and its map more seldom still.

| Part | Built in | Pages project (`config/site.toml`) | Served at |
|---|---|---|---|
| the app: page shells, code, styles, UI strings | `dist/app/` | `pages_project`, `election-map-slovakia` | `volebnamapa.sk` |
| an election's map bundle: geometry, base map, addresses | `dist/map/<slug>/` | `map_project`, `ems-map-<slug>` | the address of the deployment that carries its key |
| an election's data bundle: candidates, research, occupations, About | `dist/data/<slug>/` | `data_project`, `ems-data-<slug>` | the address of the deployment that carries its key |
| the cached copies of the pages research cites | `dist/sources/` | `sources_project`, `ems-sources` | `sources_url`, `sources.volebnamapa.sk` |
| the results of every election | `dist/results/` | `results_project`, `ems-results` | `results_url`, `results.volebnamapa.sk` |

How each is laid out is described in `src/election_map_slovakia/build.py`
(the app) and `bundle.py` (the data parts).
Each part has its own `_headers` and `404.html`,
so its file budget (20,000 files on the Free plan) is its own too.

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
  and base map extract,
  its curated obvody and okrsky,
  and the code of the steps that make the map.
  Research, links between persons, translations, party logos, results
  and the other election's data do not reach it.
- **Entwined elections:**
  each election's persons are linked to those of every other,
  with their candidacies and results there;
  the research of the latest election's candidates is reused
  for the earlier ones;
  an election's results are compared with the election's before.
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

- **A bundle**, map or data, is deployed once per key.
  The app names it by the address of that deployment,
  `https://<id>.ems-map-<slug>.pages.dev`
  or `https://<id>.ems-data-<slug>.pages.dev`,
  which keeps serving that deployment's files
  whatever is deployed after it,
  so a bundle never changes under a page that uses it,
  and its files may be kept for good (`web/_headers-data`).
  The page connects to the map's server as it loads
  (a preconnect in the shell),
  so the map's other address costs it no extra round trip.
- **The sources and the results** are served at their domains
  by their project's current production deployment,
  which is deployed anew when it carries another key.

`ems data status` says which parts are not deployed with their key,
`ems data deploy` deploys those of `dist/`
(see `src/election_map_slovakia/pages.py`).

## What runs when

| Event | Workflow | What it does |
|---|---|---|
| push to any branch, pull request from a fork | `ci.yml` | Ruff, ty, pytest and `ems data lock --check` on Python 3.11, 3.12 and 3.14; Biome on `web/`. Nothing is downloaded or built. |
| push of a tag `vX.Y.Z` | `release.yml` | the checks of `ci.yml`; then what changed is built and deployed |

`release.yml` runs these jobs:

1. **ci**: the checks above.
2. **plan**:
   checks that the tag matches `__version__`
   in `src/election_map_slovakia/__init__.py`,
   and asks the Pages API which data parts are not deployed
   with their key in `data/published.toml` (`ems data status`).
3. **data**, only if any:
   - downloads the pinned inputs (`ems fetch`),
     from the input store where they are not in the Actions cache
     (keyed by `config/inputs.toml`);
   - builds and checks the whole site (`ems make`);
   - deploys each data part whose key is not deployed yet
     (`ems data deploy`).
4. **app**, after the data or without them:
   - builds the app for the deployed data parts
     (`ems build --deployed`):
     each election's bundles are the deployments that carry their keys,
     whose `manifest.json` gives each one's version and files;
   - checks it, against those files (`ems check`);
   - deploys `dist/app/` to `pages_project`
     as a production deployment of the branch `main`.
5. **github-release**: creates the GitHub release of the tag
   with generated notes and the app's files attached
   (`election-map-slovakia-X.Y.Z.tar.gz`).

A release that changes no data skips the data job
and takes a few minutes;
one that changes data fetches about 1 GB from the store
and builds the whole site, as `ems make` does locally.
A failed job can be re-run from the run's page;
anything that needs a code change is a new version.

## Releasing

```sh
# set __version__ in src/election_map_slovakia/__init__.py, add the
# version's section to CHANGELOG.md; after a change to the data, also
uv run ems make
uv run ems data lock
# commit (with data/published.toml), then:
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
whatever its source serves now or whether it still serves it.
`ems fetch` takes a pinned file from `data/raw/` where it is there,
else from the store (no login needed),
else from its source; the digest is checked either way.

When a source publishes a new version of an input:

```sh
uv run ems inputs update addresses   # download, check, write the new pin
uv run ems inputs publish            # upload the files the store lacks
uv run ems make                      # build with it
uv run ems data lock                 # the keys it changes
git commit config/inputs.toml data/published.toml
```

`ems inputs publish` uses the GitHub CLI (`gh`),
logged in as a user who may write to the repository's releases.
It uploads nothing twice and replaces nothing.

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
4. **Repository secrets**
   (Settings › Secrets and variables › Actions):
   `CLOUDFLARE_API_TOKEN` (the token)
   and `CLOUDFLARE_ACCOUNT_ID`
   (shown on the account's Workers & Pages overview).
   Locally, `ems build --deployed`, `ems data status`, `ems data deploy`,
   `ems results deploy` and `scripts/pages_trial.py`
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

6. **Pages projects**, one per part,
   all with the production branch `main`,
   the branch every deployment is made as:

   ```sh
   npx wrangler pages project create election-map-slovakia --production-branch=main
   npx wrangler pages project create ems-map-2026 --production-branch=main
   npx wrangler pages project create ems-map-2022 --production-branch=main
   npx wrangler pages project create ems-data-2026 --production-branch=main
   npx wrangler pages project create ems-data-2022 --production-branch=main
   npx wrangler pages project create ems-sources --production-branch=main
   npx wrangler pages project create ems-results --production-branch=main
   ```

   Or in the dashboard: Workers & Pages › Create › Pages › Upload assets.
   A new election adds `ems-map-<slug>` and `ems-data-<slug>`.
   If a name's `pages.dev` host is taken,
   Pages adds a suffix to it; the project keeps its name.
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
   - `ems-results`: `results.volebnamapa.sk` (`results_url`).

   With the zone on Cloudflare the DNS records are created automatically.
   The bundles need no domain.
3. **One address.**
   In the zone, a redirect rule (Rules › Redirect Rules)
   from `www.volebnamapa.sk` to `https://volebnamapa.sk`,
   keeping the path and query, so that the site has one address.
   To send the visitors of `<project>.pages.dev` there as well,
   add a Bulk Redirect from it.

Moving to another domain later is a new `base_url` and a new release;
the sources and the results move with new `sources_url` and `results_url`,
which change no key.

## Results

The election results are a part of their own, `results/<election day>/`
([results.md](results.md)),
which the app reads from `results_url`,
and which the CSP's `connect-src` lets it.
`ems make` writes the final results from their pinned inputs,
and a release deploys them with their key.
On a future election night they change every few minutes:
`ems results poll --deploy` (or `ems results deploy` by hand)
then writes the results part locally
and deploys it to `results_project`, without a release,
carrying the locked results key followed by `live`
([the night's steps](results.md#a-future-election-night)).
A release that night, of the app for one,
finds that key deployed and leaves the live results in place;
the release that pins the final results changes the key,
and deploys them.

### Polling: `live`

Polling is switched per election by `live` in `config/elections.toml`.

- **On:** the app reads the results only from the polls' closing
  (`polls_close`), every minute while the page is in view,
  for `live_days` (7) days.
  Before that it reads nothing, after that once per page load
  (`liveWindow` in the shells' config),
  so that a page left open, or an old copy of the site in a cache,
  stops polling while the final results stay shown.
- **Off** (as once the final results are in a release):
  it reads them once per page load at any time.
- **`EMS_RESULTS_ANYTIME=1`:** a build with it polls at any time,
  for testing, whatever `live`.

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
- **A bundle:** fetched with `?v=` its version
  (a hash of its files, in its `manifest.json`)
  from an address that always serves the same files,
  so kept for good (`web/_headers-data`).
- **The results:** `status.json` revalidated on every load,
  every other file fetched with `?v=` its hash and kept a day
  (`web/_headers-results`;
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
since it names each bundle by its deployment.
The sources and the results roll back on their own projects;
the next release deploys them again
if their current deployment does not carry the locked key.

## By hand

The same build locally, then a look at the result:

```sh
uv run ems fetch
uv run ems make
uv run ems serve
```

`ems serve` serves the parts as one site,
where an app built without `--deployed` finds them:
each bundle at `/map/<slug>/` or `/data/<slug>/`, the results at `/results/`,
the cached copies at `/cache/`.

Deploying by hand, with the API token and account in the environment
(or after `npx wrangler login`, for Wrangler alone):

```sh
uv run ems data status           # what is not deployed
uv run ems data deploy           # the data parts of dist/ not deployed
uv run ems build --deployed      # the app for them
uv run ems check
npx wrangler pages deploy dist/app --project-name=election-map-slovakia --branch=main
```
