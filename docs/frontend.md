# The frontend

`web/` holds the frontend. `app.css` and `js/` (ES modules, no build step)
are copied to `/assets/<v>/`, `vendor/` (Leaflet 1.9.4, its
`dist/leaflet.js` less the source-map comment since the map is not shipped;
Preact + htm; the QR code generator) to `/assets/vendor/<vv>/` and `img/`
(party logos) to `/assets/img/<iv>/`, each version a hash of its tree
(`cache.css`, the cached copies' stylesheet, to `/assets/`). The modules
import the libraries as `'../vendor/…'`, so `web/` runs as it is, and the
build rewrites that prefix to `/assets/vendor/<vv>/` (in the modules
directly in `js/`, where it means `web/vendor/`).
`index.html` (app shell) and `picker.html` (root page) are templates, and
`i18n/<lang>.json` holds the hand-written UI strings, Slovak and English
(the build adds the other languages' and the occupations' translations;
the card and the tooltip of a translated occupation give the Slovak
original; party names stay as the official lists write them).
`app.description` is the search engines' description of a page, and
`app.features`, what the site offers in a paragraph, is on the root page in
each fallback language and in an app shell's `<noscript>`, for search
engines that do not run the page's scripts. The whole page is the map; the
site name with the search, round buttons for language, boundaries,
light/dark theme and Favourites, zoom and help (the disclaimer, and from
there the About dialog) float on it. While the polls are open (site.toml
`polls_open`, `polls_close`), a line under the site name says the voting
is under way, with a still bar of how much of the voting day has passed;
once counting starts, the count's status takes its place (`js/live.js`
`LiveStatus`, how far each election has got by the registered voters
whose polling districts are counted). Clicking a place or a search result
opens a pane with the ballots there (a bottom sheet on phones); it closes
with its button, Esc or, on phones, a swipe down. A contest's header shows
whether it is open: tinted when open; muted, with a grey bar at its side
for the candidates it hides, when closed; its tooltip says what a press
does. At its end a short horizontal meter (`Turnout` in `js/ballots.js`)
gives the turnout of the last election in the contest's area (2022, or a
municipal by-election since; a council's of the whole municipality where
it now has several constituencies, whose 2022 boundaries differ; a
regional constituency's summed over its municipalities), the share and
the year above it, without making the header taller; the tooltip gives
the numbers. Once the contest is counted, the meter shows the 2026
turnout in the results' green, the last election's as a grey tick on the
track with its figures under it. A candidate's
ballot number circles the candidate (`js/picks.js`), as voters circle
numbers on the ballot: a contest lists its circled candidates even when
closed, the filter never mutes them, and its header counts them, flagging
the number of seats when more are circled than are elected (which on the
ballot itself would make it invalid). Every button on a row has an
alternate press, Shift+click or a double click or tap (the only one a
phone has; `useRowActions` in `js/ballots.js`): on the number it crosses
the candidate out with a red cross, which the filter then mutes like any
it excludes (the filter bar counts them, and clearing it clears them); on
a party tag or a mark it adds the party or mark to the filter with its
candidates hidden, where a plain press shows only them; each press,
repeated, undoes itself. With Shift held, the button under the pointer
previews the alternate press: a faint cross on a number, a faint dashed
ring on a party tag or mark (the root element has the class `shift`).
On a candidate card each of
the candidate's contests starts closed, showing just the candidate (and
those circled); its header opens it to the others, whom the filter applies
to (never to the candidate, who stays first), and its pin, in the colour
the area is drawn in on the map, shows the
municipality, city district, constituency or, in Bratislava and Košice, the
city or its council constituency, or for a regional contest the
self-governing region or its regional constituency on the map while the
card stays open. On the ballots of a place and in Favourites the same pin
fits the map to the contest's area and highlights it in its colour beside
the place, which stays selected, its ballots and the list as they are,
until another place is (`fitArea` in `js/map.js`, draw.js `showArea`).
Once the
contest is counted, the pin's next press colours that area by the
contest's 2026 turnout, in the colour the area is drawn in (the pin filled
with it while it does), and another takes it off (`ContestMapButton` in
`js/mapmode.js`).
Favourites (`js/favourites.js`) lists every circled
candidate's contest the same way, the circled first, with buttons by its
title that copy a link to them and the filter alone, with the list open,
or show that link as a large QR code in a dialog of its own, for another
device's camera (the encoder, `vendor/qrcode-generator.module.js`, loads on
first use). It opens only
with its button: from 960 px wide as a pane of its own
beside the first, as the search results are, as wide as the page allows,
where a candidate chosen opens in the first pane and a map click or a
contest's pin keeps the list open, but a place found by the search closes
it, as it would hide that place. Narrower, it is what the pane shows, as
wide as the page allows on a tablet; a phone's sheet leaves the place in
view above the list. The theme follows the device
unless chosen in the theme menu (kept in localStorage); `js/theme.js`
applies it before the first paint.
The map uses Leaflet for the view, without any tile layer, and one canvas
of its own, drawn in a worker (`js/render.js` running `js/draw.js`) so that
fetching, decoding and drawing never hold up the page's main thread: it
only moves and scales the canvas with the gesture and swaps in each
finished drawing. The background is our own geometry, loaded per okres and
level of detail as the view changes and kept as typed arrays in a cache
bounded by size (`js/topo.js`), with labels and, from zoom 16, house
numbers, all in the theme's colours. The countries around Slovakia are drawn
below it, duller, with dashed borders and their names where most of each
shows; they cannot be clicked, and the lowest zoom keeps every view within
them. Areas are only filled; every border is stroked once from the
topology, in the style of the highest boundary it is part of; a dashed one
is cut into its dashes only where the drawing shows it (the canvas would
dash it whole, far beyond the view when zoomed in). Zoom is continuous
(`js/zoom.js`): wheel, trackpad, pinch, buttons and double-click scale the
canvas every frame. While a pan or zoom goes on, the view is drawn again at
a lower resolution whenever the last drawing no longer covers it, and sharp
once the gesture settles; what has not loaded yet is added as it comes.
The 2026 results can colour the map (`js/mapmode.js`): a candidate's share
of the votes by area, from a pin at the end of their row, which also
fits the map to the contest's area: across its areas where it spans
several (a regional contest, or Bratislava's or Košice's city contests by
city district), else over its one area (a mayor's municipality, a
council's municipality or council constituency, in the strongest step,
there being nothing to compare it with); or, from the
boundaries menu once counting has started, the turnout of the municipal
elections (every okres file of the live results: each municipality, and
each district of Bratislava and Košice, by its own mayor and council), of
the two cities' own elections of a city mayor and council, on ballots of
their own (the city files; by district where the mayor's contest has
them, else the city alike), or of the regional elections. Each
municipality, or on election night each regional
constituency known only as a whole, takes one of six steps of a colour
(a candidate's votes the results' green, `--map-result-*`; a turnout the
colour its area is drawn in, mixed into the land: the municipalities' red,
a council constituency's orange, the cities' green, a regional contest's
violet) on a scale that spans the values shown, in whole
percentage points (30–50 % where every area lies between them, not
0–50 %), the areas not counted yet left out of it and uncoloured, below the
municipalities' zoom each regional constituency as its municipalities
together; borders and labels stay above, and each value is a label of its
own under the name or number of its area, which stays where it was. A
legend on the map (under the search card on phones) names what is shown,
gives the scale and the overall figure, and turns it off; it all follows
the live results as they change. The selected place, candidate, Favourites
and the About dialog are kept in the URL hash, so links can be shared, and
so are the circled candidates and the filter, though Back and Forward leave
those as they are (`js/app.js`).
The About dialog (`js/about.js`) is a short page with the project's
purpose, the source code, the version (a link to its GitHub release) and
the license, and links to its sections (`#v=about-method`, `-sources`,
`-research`, `-disclaimers`). The site makes no requests to other servers
but for the live results (`live_url` in `config/site.toml`, in the shell's
config as `live`); `web/_headers` (the base of `dist/_headers`, the build
adds the live origin to its connect-src) sets a Content-Security-Policy
that lets the browser enforce this. Code, libraries and images are under
their versioned directories, kept by browsers for good, and every JSON
file is fetched with `?v=` and the build's data version (`dataVersion` in
the shell's config; `dataUrl` in `js/files.js`), kept a day, so a release
reaches visitors on their next page load (`build.py`, "Cache busting").
