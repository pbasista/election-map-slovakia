# Releases and deployment

The site is hosted on Cloudflare Pages and deployed from GitHub Actions; both
fit their free plans.

## What runs when

| event | workflow | what it does |
|---|---|---|
| push to any branch, pull request from a fork | `ci.yml` | Ruff, ty and pytest on Python 3.11, 3.12 and 3.14; Biome on `web/`. Nothing is downloaded or built. |
| push of a tag `vX.Y.Z` | `release.yml` | the checks of `ci.yml`; then the site is built and deployed |

`release.yml`, step by step, each starting only after the one before it
succeeded:

1. **ci** — the checks above.
2. **build** — checks that the tag matches `__version__` in
   `src/election_map_slovakia/__init__.py`, downloads the official inputs
   (`ems fetch`, with `data/raw/` kept in the Actions cache), builds and
   checks the site (`ems make`) and keeps `dist/` and its archive
   `election-map-slovakia-X.Y.Z.tar.gz` as workflow artifacts.
3. **deploy** — uploads `dist/` to the Cloudflare Pages project
   (`pages_project` in `config/site.toml`) with Wrangler, as a production
   deployment of the branch `main`.
4. **github-release** — creates the GitHub release of the tag with
   generated notes and the archive attached.

A failed job can be re-run from the run's page; anything that needs a code
change is a new version.

## Releasing

```sh
# set __version__ in src/election_map_slovakia/__init__.py, add the
# version's section to CHANGELOG.md, commit, then:
git tag v0.1.0
git push origin main v0.1.0
```

## Setup, once

1. **GitHub.** A public repository: the About dialog links to it, and it is
   where mistakes are reported. Actions minutes are free for public
   repositories, and the `production` environment the deploy job reports
   to is available on every plan for them.
2. **Cloudflare Pages project.** Its name is `pages_project` in
   `config/site.toml` (`election-map-slovakia`):

   ```sh
   npx wrangler pages project create election-map-slovakia --production-branch=main
   ```

   or in the dashboard: Workers & Pages › Create › Pages › Upload assets.
   The production branch must be `main`, the branch every release is
   deployed as. If `election-map-slovakia.pages.dev` is taken, Pages adds a
   suffix to the host name; the site then lives there.
3. **API token.** Cloudflare dashboard › My Profile › API Tokens › Create
   Token › Custom token, permission *Account › Cloudflare Pages › Edit*.
4. **Repository secrets** (Settings › Secrets and variables › Actions):
   `CLOUDFLARE_API_TOKEN` (the token) and `CLOUDFLARE_ACCOUNT_ID` (shown on
   the account's Workers & Pages overview).

## The domain

The site's domain is `volebnamapa.sk` (`base_url` in `config/site.toml`).
Every page names its address there as canonical, the language links are
absolute, and `dist/_headers` answers on `<project>.pages.dev` and every
`<hash>.<project>.pages.dev` with `X-Robots-Tag: noindex`, so search engines
list the site only under its domain. Those addresses keep working.
`sitemap.xml` lists the root page and every language's page under the
domain: submit `https://volebnamapa.sk/sitemap.xml` to Google Search
Console, Bing Webmaster Tools and Seznam Webmaster.

Setup, once, after the Pages project exists:

1. **DNS on Cloudflare.** A Pages project can serve an apex domain only
   from a zone on Cloudflare: add `volebnamapa.sk` to the Cloudflare account
   (the Free plan does) and change its name servers at the registrar to the
   two that Cloudflare names.
2. **Custom domains.** In the Pages project: Custom domains › Set up a
   custom domain, `volebnamapa.sk`; with the zone on Cloudflare the DNS
   record is created automatically. Add `www.volebnamapa.sk` the same way,
   so that the address people type out of habit works too.
3. **One address.** In the zone, a redirect rule (Rules › Redirect Rules)
   from `www.volebnamapa.sk` to `https://volebnamapa.sk`, keeping the path
   and query, so that the site has one address. To send the visitors of
   `<project>.pages.dev` there as well, add a Bulk Redirect from it.

Moving to another domain later is a new `base_url` and a new release.

## By hand

The same build locally, then a look at the result:

```sh
uv run ems fetch
uv run ems make
uv run ems serve
```

A manual upload of a checked `dist/`:

```sh
npx wrangler pages deploy dist --project-name=election-map-slovakia --branch=main
```
