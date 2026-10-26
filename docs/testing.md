# Testing

The checks that CI runs, and how to see a change in a real browser: the
built site served locally, with its final results or dummy ones if the
change concerns them, driven by a headless Chromium or Firefox.

## Checks

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -q
npx --yes @biomejs/biome@2.5.12 ci
uv run ems build && uv run ems check
```

Their output is long; to keep it, send it to a log and read the log only
when a check fails, rather than running it again:

```sh
uv run pytest -q > /tmp/ems-pytest.log 2>&1; echo rc=$?
```

## The site locally, with results

```sh
uv run ems make                         # the final results of the inputs
EMS_RESULTS_ANYTIME=1 uv run ems build  # read them at any time
uv run ems serve --port 8765 &          # dist/, the results in it
```

The site reads its results from `dist/results/<election day>/` on the same
server, so one server is all it takes. A plain build reads them once per
page load (with `live` off in site.toml, or past the polls' closing plus
`live_days`), which also works; `EMS_RESULTS_ANYTIME=1` polls at any
time. For dummy results in place of the final ones:

```sh
uv run ems results fake mid             # none, early, mid, late or final
EMS_RESULTS_ANYTIME=1 uv run ems build
```

The stages and what each holds are in
[results.md](results.md#testing-the-app-with-dummy-results). Start
`ems serve` after the build, since it reads `dist/_headers` once, at
startup.

Places worth opening (`/en/#…`):

| Hash | What |
|---|---|
| `o=500011` | Nitra: a council in several constituencies, a city mayor, the regional contests |
| `o=528595` | Bratislava-Staré Mesto: a city district, with the city's own contests |
| `o=520071` | a municipality in the regional constituency that `fake` decides by a landslide at `mid` |
| `o=528595&f=1&k=oz:500011/3.1,starosta:500011.1` | the same district with Favourites open, two Nitra candidates circled |

`k` lists circled candidates as `<contest>.<ballot numbers>`, contests
comma-separated; `f=1` opens Favourites.

## A headless browser

Playwright for Python, as a one-off: `uv run --no-project --with` gives
it to a single run, so the project gains no dependency. The first time,
fetch its Chromium (into `~/.cache/ms-playwright/`):

```sh
uv run --no-project --with playwright==1.56.0 python -m playwright install chromium
```

Then a script such as this one, run with
`uv run --no-project --with playwright==1.56.0 python check.py`:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1600, "height": 950}, reduced_motion="reduce"
    )
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto("http://127.0.0.1:8765/en/#o=500011")
    page.locator(".ballots .contest-map").nth(9).click()  # a contest's pin
    page.wait_for_timeout(2500)  # the map's fit and redraw
    page.screenshot(path="/tmp/ems-check.png")
    print("errors:", errors)
    browser.close()
```

Notes:

- `reduced_motion="reduce"` turns the page's own transitions off
  (`prefers-reduced-motion` in `app.css`), so screenshots do not catch
  them half-way. Injecting a style to the same end fails: the CSP allows
  no inline style.
- The width decides the layout (`js/pane.js`): up to 640 px the pane is a
  bottom sheet; below 960 px one pane, which Favourites take over when
  open; from 960 px Favourites stand in a pane of their own beside it.
- The map fits with an animation and draws in a worker, off the DOM: wait
  a moment after a press before a screenshot, and check the map on the
  image, not in the DOM.
- Useful selectors: `.ballots .contest-map` and
  `.favourite-contests .contest-map` a contest's pin, `.votes-map` a
  candidate's, `.map-legend` the legend of what the map colours by,
  `.live-status` and `.voting-bar` the status line under the title.
- A browser already running can be driven instead, e.g. Chromium started
  with `--headless=new --remote-debugging-port=9222`, by
  `p.chromium.connect_over_cdp("http://127.0.0.1:9222")` and pages from
  `browser.new_context(viewport=…, reduced_motion="reduce")`.

### Firefox

The same script runs in Firefox with `p.firefox.launch()` in place of
`p.chromium.launch()`, after fetching Playwright's Firefox once:

```sh
uv run --no-project --with playwright==1.56.0 python -m playwright install firefox
```

That is a Firefox built for Playwright (142 for 1.56), not the one
installed on the system, which Playwright cannot drive and which may be
newer; for a look at that one, open the local site in it by hand. To run
one check in both engines, take the engine's name from the command line:

```python
import sys

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = getattr(p, sys.argv[1]).launch()  # chromium or firefox
    ...
```

```sh
for b in chromium firefox; do
  uv run --no-project --with playwright==1.56.0 python check.py $b
done
```

The README's screenshot has a script of its own, with no dependency
beyond a Chromium-family browser: `scripts/screenshot.py`.

## Afterwards

Put the results and `dist/` back to the real state and stop the server:

```sh
uv run ems make
```
