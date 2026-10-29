# Testing

Two kinds of testing:

- **the checks** that CI runs ([deploy.md](deploy.md#what-runs-when));
- **a real browser**: the built site served locally,
  with its final results or dummy ones if the change concerns them,
  driven by a headless Chromium or Firefox.

## Checks

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -q
npx --yes @biomejs/biome@2.5.12 ci
uv run ems build && uv run ems check
```

Their output is long.
To keep it, send it to a log and read the log only when a check fails,
rather than running it again:

```sh
uv run pytest -q > /tmp/ems-pytest.log 2>&1; echo rc=$?
```

## The site locally, with results

```sh
uv run ems make                         # the final results of the inputs
EMS_RESULTS_ANYTIME=1 uv run ems build  # read them at any time
uv run ems serve --port 8765 &          # the parts of dist/ as one site
```

`ems serve` serves the parts of `dist/` as one site
([pipeline.md](pipeline.md#serve)):
the app at `/`, each election's bundles at `/map/<slug>/` and `/data/<slug>/`,
the results at `/results/` (the site reads `/results/<election day>/`)
and the cached copies of sources at the root,
so one server is all it takes.
A plain build reads the results once per page load,
which also works;
`EMS_RESULTS_ANYTIME=1` polls at any time
(when the app polls: [deploy.md](deploy.md#polling-live)).

For dummy results in place of the final ones:

```sh
uv run ems results fake mid             # none, early, mid, late or final
EMS_RESULTS_ANYTIME=1 uv run ems build
```

The stages and what each holds are in
[results.md](results.md#testing-the-app-with-dummy-results).
Start `ems serve` after the build,
since it reads each part's `_headers` once, at startup.

### Places worth opening

Open them as `/en/#…`:

| Hash | What |
|---|---|
| `o=500011` | Nitra: a council in several constituencies, a city mayor, the regional contests |
| `o=528595` | Bratislava-Staré Mesto: a city district, with the city's own contests |
| `o=520071` | a municipality in the regional constituency that `fake` decides by a landslide at `mid` |
| `o=528595&f=1&k=oz:500011/3.1,starosta:500011.1` | the same district with Favourites open, two Nitra candidates circled |

`k` lists circled candidates as `<contest>.<ballot numbers>`,
contests comma-separated; `f=1` opens Favourites.

## A headless browser

### Setup

Use Playwright for Python as a one-off:
`uv run --no-project --with` gives it to a single run,
so the project gains no dependency.
The first time, fetch its Chromium (into `~/.cache/ms-playwright/`):

```sh
uv run --no-project --with playwright==1.56.0 python -m playwright install chromium
```

### A script

Run a script such as this one with
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
    page.locator(".ballots .turnout-map").nth(9).click()  # a contest's turnout
    page.wait_for_timeout(2500)  # the map's fit and redraw
    page.screenshot(path="/tmp/ems-check.png")
    print("errors:", errors)
    browser.close()
```

### Notes

- **Motion.**
  `reduced_motion="reduce"` turns the page's own transitions off
  (`prefers-reduced-motion` in `app.css`),
  so screenshots do not catch them half-way.
  Injecting a style to the same end fails:
  the CSP allows no inline style.
- **Layout.**
  The width decides the layout (`js/pane.js`):
  up to 640 px the pane is a bottom sheet;
  below 960 px one pane, which Favourites take over when open;
  from 960 px Favourites stand in a pane of their own beside it.
- **The map** fits with an animation and draws in a worker, off the DOM:
  wait a moment after a press before a screenshot,
  and check the map on the image, not in the DOM.
- **Useful selectors:**

  | Selector | Element |
  |---|---|
  | `.ballots .turnout-map`, `.favourite-contests .turnout-map` | a contest's turnout on the map |
  | `.winner-map` | who got the most votes where |
  | `.votes-map` | a candidate's votes on the map |
  | `.map-legend` | the legend of what the map colours by |
  | `.live-status`, `.voting-bar` | the status line under the title |

- **A running browser** can be driven instead,
  e.g. Chromium started with `--headless=new --remote-debugging-port=9222`,
  by `p.chromium.connect_over_cdp("http://127.0.0.1:9222")`
  and pages from `browser.new_context(viewport=…, reduced_motion="reduce")`.

### A phone

A context such as
`browser.new_context(viewport={"width": 390, "height": 844},
is_mobile=True, has_touch=True, device_scale_factor=2,
reduced_motion="reduce")`
has the phone layout and a touch screen without hover, `(hover: none)`,
which the tap on the map depends on.
Its states and what to look for:

- **The sheet:** `.side .pane` with `sheet-peek`, `sheet-half`
  or `sheet-full`,
  its height in `--sheet-height` on the root element.
  A place opens at half; results put on the map from it lower it to peek.
  `.pane-grip` is a button that steps through the heights (Enter works).
  To drag it, send touches through a CDP session
  (`ctx.new_cdp_session(page)`, `Input.dispatchTouchEvent`
  with `touchStart`, a few `touchMove`s and `touchEnd`);
  a quick stroke goes to the next height,
  a drag down from peek closes the sheet.
- **The legend:** without the sheet `.map-legend.pill`,
  unfolded by `.map-legend-unfold` and folded again by `.map-legend-fold`;
  with the sheet open, `.map-legend.bar` in `.pane-top`,
  `.map-legend-fold` showing its units sentence.
- **The map card:** with results on the map,
  `page.touchscreen.tap(x, y)` on a coloured area shows `.map-card`,
  whose `.map-card-ballots` picks the place.
- **More controls:** with the sheet open,
  `.controls-more` puts out the language, boundaries, theme
  and Favourites buttons.
- **The credits,** `.leaflet-control-attribution`,
  show in full for five seconds or until the map is touched,
  then fold to `.km-credits-button` (class `folded`);
  the button unfolds them.

### Firefox

The same script runs in Firefox with `p.firefox.launch()`
in place of `p.chromium.launch()`,
after fetching Playwright's Firefox once:

```sh
uv run --no-project --with playwright==1.56.0 python -m playwright install firefox
```

That is a Firefox built for Playwright (142 for 1.56),
not the one installed on the system,
which Playwright cannot drive and which may be newer;
for a look at that one, open the local site in it by hand.

To run one check in both engines,
take the engine's name from the command line:

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

### The README's screenshot

It has a script of its own,
with no dependency beyond a Chromium-family browser:
`python3 scripts/screenshot.py` after `uv run ems build`
(`--browser PATH` where none is on `PATH`;
arguments after `--` go to the browser).

## Afterwards

Put the results and `dist/` back to the real state and stop the server:

```sh
uv run ems make
```
