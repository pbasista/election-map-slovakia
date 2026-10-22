# Election Map Slovakia

A zoomable map of every constituency of the Slovak municipal and regional
elections of 24 October 2026, with the candidates standing in each. Click a
place or search for an address, a municipality or a candidate to see every
ballot voted on there; a candidate card adds AI-researched, source-linked
notes on the candidate's career and controversies. It is at
**<https://volebnamapa.sk>**.

![The map around Banská Bystrica, its council constituency No. 1 highlighted where the visitor clicked, and beside the map the ballots voted on there with the candidates in ballot order, their parties and marks](docs/img/main.png)

It is a static site: a Python pipeline turns official open data into plain
files, served as they are by Cloudflare Pages. The browser loads nothing from
other servers.

## Install

You need [git](https://git-scm.com/) and
[uv](https://docs.astral.sh/uv/getting-started/installation/); uv brings
the Python (3.11 or newer) and the packages.

```sh
git clone https://github.com/pbasista/election-map-slovakia.git
cd election-map-slovakia
uv sync
```

## Run

```sh
uv run ems fetch     # download the official inputs into data/raw/ (about 230 MB)
uv run ems make      # build the site into dist/ and check it
uv run ems serve     # serve it at http://127.0.0.1:8000/
```

Then open <http://127.0.0.1:8000/> in a browser. After changing `config/`,
`data/curated/` or `web/`, run `uv run ems make` again; it redoes only the
steps whose inputs changed.

## Documentation

- [docs/pipeline.md](docs/pipeline.md) — every `ems` command, what each step
  makes, and the configuration files
- [docs/frontend.md](docs/frontend.md) — how the page works
- [docs/agent-jobs.md](docs/agent-jobs.md) — translations, constituency
  rules and candidate research by AI agents
- [docs/deploy.md](docs/deploy.md) — CI, releases, Cloudflare Pages and the
  site's own domain
- [CHANGELOG.md](CHANGELOG.md)

## Development

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
npx --yes @biomejs/biome@2.5.12 ci
```

A push to any branch runs these checks; a version tag builds the site and
deploys it ([docs/deploy.md](docs/deploy.md)).

The screenshot above, `docs/img/main.png`, is taken from the built site by
`python3 scripts/screenshot.py` (after `uv run ems build`). It needs only
a Chromium-family browser, found on `PATH` or passed with `--browser`.

## License

EUPL-1.2, see [LICENSE](LICENSE). The data sources and their licenses are
listed in [NOTICE](NOTICE).
