# Election Map Slovakia

A zoomable map of every constituency
of the Slovak municipal and regional elections of 24 October 2026,
with the candidates standing in each and their results.
It is at **<https://volebnamapa.sk>**.

![The map around Banská Bystrica, its council constituency No. 1 highlighted where the visitor clicked, and beside the map the ballots voted on there with the candidates in ballot order, their parties and marks](docs/img/main.png)

## Features

- **Ballots by place.**
  Click the map, or search for an address, a municipality or a candidate,
  to see every ballot voted on there.
- **Candidate notes.**
  A candidate card adds AI-researched, source-linked notes
  on the candidate's career and controversies.
- **Favourites.**
  Circle candidates' numbers as on the ballot to gather them in one list,
  which a link (or its QR code) shares.
- **Results.**
  Each candidate's votes, the turnout and the winners,
  on the ballots and on the map, down to the polling districts;
  shown live as they were counted on election night.
- **Nine languages,** a light and a dark theme, phones and desktops.
- **Static and self-contained.**
  A Python pipeline turns official open data into plain files,
  served as they are by Cloudflare Pages.
  The browser loads nothing from other servers, the results included.

## Quick start

You need [git](https://git-scm.com/) and
[uv](https://docs.astral.sh/uv/getting-started/installation/);
uv brings Python (3.11 or newer) and the packages.

```sh
git clone https://github.com/pbasista/election-map-slovakia.git
cd election-map-slovakia
uv sync

uv run ems fetch     # download the official inputs into data/raw/ (about 230 MB)
uv run ems make      # build the site into dist/ and check it
uv run ems serve     # serve it at http://127.0.0.1:8000/
```

Then open <http://127.0.0.1:8000/>.
After changing `config/`, `data/curated/` or `web/`,
run `uv run ems make` again:
it redoes only the steps whose inputs changed.

## Documentation

| Document | What it covers |
|---|---|
| [docs/pipeline.md](docs/pipeline.md) | Every `ems` command, what each step makes, identifiers, configuration |
| [docs/frontend.md](docs/frontend.md) | How the page works: layout, ballots, map, results on the map, caching |
| [docs/results.md](docs/results.md) | The election results: commands, file format, sources, an election night |
| [docs/agent-jobs.md](docs/agent-jobs.md) | Translations, constituency rules and candidate research by AI agents |
| [docs/deploy.md](docs/deploy.md) | CI, releases, Cloudflare Pages and the site's domain |
| [docs/testing.md](docs/testing.md) | The checks, and the site in a headless browser with real or dummy results |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

## Development

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
npx --yes @biomejs/biome@2.5.12 ci
```

A push to any branch runs these checks;
a version tag builds the site and deploys it
([docs/deploy.md](docs/deploy.md)).
To see a change in a browser, see [docs/testing.md](docs/testing.md).

The screenshot above is taken from the built site
by `python3 scripts/screenshot.py` (after `uv run ems build`):
the page as on the day before the elections,
without the voting line and the results.
It needs only a Chromium-family browser,
found on `PATH` or passed with `--browser`.

## Data and licence

The code is licensed under the EUPL-1.2, see [LICENSE](LICENSE).
The data sources, their licences and the vendored libraries
are listed in [NOTICE](NOTICE).
