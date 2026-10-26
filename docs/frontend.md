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
after they close, while nothing is counted yet (status phase `none`, or
no results to read yet) and the results are still polled, it says
that the results are awaited and will appear as they come in; once
counting starts, the count's status takes its place (`js/live.js`
`LiveStatus`, how far each election has got by the registered voters
whose polling districts are counted). Clicking a place or a search result
opens a pane with the ballots there (a bottom sheet on phones); it closes
with its button, Esc or, on phones, a swipe down. A contest's header shows
whether it is open: tinted when open; muted, with a grey bar at its side
for the candidates it hides, when closed; its tooltip says what a press
does. At its end a short horizontal meter (`Turnout` in `js/ballots.js`)
gives the turnout of the last election in the contest's area (2022, or a
municipal by-election since; a council's, where it now has several
constituencies, of the polling districts that make up the constituency
where they are known and the same as then, else of the whole municipality,
the 2022 constituencies being drawn otherwise; a regional constituency's
summed over its municipalities), the share and
the year above it, without making the header taller; the tooltip gives
the numbers. Once the contest is counted, the meter shows the 2026
turnout in the results' green, the last election's as a grey tick on the
track with its figures under it. Where a contest is counted but its
candidates' votes are not there yet (on election night a municipality's
turnout, its winners at most, until ŠÚ SR publishes the candidates'
votes; or a count with the turnout alone), a note above its candidates
says so in words (`nightNote` in `js/ballots.js`). On a partial count of
a council (`oz`, `zsk`), the first `seats` candidates by votes, those who
would win a seat so far, have their numbers in the results' green, and a
dashed green line labelled "↑ seats: N" follows the last of them where a
candidate who would not comes next (`seatPlaces`; a screen reader hears
each one's place, the label's tooltip explains it); not once it is final,
its elected marked. Where the place lies in units of the
contest's area with figures of their own in the final results (live.js
`placeResults`: the municipality or city district of a regional or
Bratislava's or Košice's city contest, from its `areas` entry; the council
constituency of a municipality split into several, its polling districts
summed, for any contest but that constituency's own council; the polling
district of an address or a map pick), a compact choice under the header
("Whole contest | <municipality> | Constituency No. k | Polling district
No. n", only those that differ from the whole and from each other)
switches the candidates' votes, shares and bars and the turnout meter to
that unit (with its 2022 municipal turnout in a municipal contest where
the polling district is the same as then; none for the other units). The
choice is one for every contest of the ballots, kept while browsing
places: a contest without the unit chosen shows the finest it has that is
not finer. It starts at the whole contest. A candidate's
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
`js/mapmode.js`); while the map shows another of the contest's results,
its first press does so at once. The map is fitted to a contest's area
when the results shown become that contest's (from none, a turnout layer
or another contest), not when they switch between its candidates, its
turnout and who got the most votes, nor as zooming changes their units:
the view the visitor zoomed to stays.
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
A faint base map helps find a neighbourhood (`base/`, built by `ems
basemap` from OpenStreetMap, no tiles from other servers): rivers, larger
streams, lakes and reservoirs, roads by class and railways, loaded with the
shards (a file per okres at their level of detail, cached like them;
`base/coarse.json`, motorways, major rivers and lakes, with the coarse
view). Draw.js (`drawBase`) draws it over the land and the results' fills
and below every border, highlight and label, in the theme's
`--map-base-*` colours (a blue for the waters, warm greys for the roads, a
grey for the railways) at the theme's `--map-base-alpha` (0.5 light, 0.6
dark), from paths made once per bin and class and scaled by the
transform. Line widths grow with the zoom by class (`BASE_LINES`):
motorways, expressways and rivers from the lowest zoom, primary and
secondary roads, railways and canals from 9, tertiary roads, trams and
streams from 12, minor streets only from 13, their mesh greying the towns
below that. Below zoom 16 the dense classes (minor and tertiary streets,
streams, railways) are hairlines of one canvas pixel: stroked wider, they
took most of a drawing's time in a city. The layers menu switches it off
("Base map").
The okrsky (polling districts) of the municipalities whose okrsky are
known are an overlay of their own in the boundaries menu
(`geo/okrsky/<okres>/<lod>.json`, from zoom 13): thin blue lines inside
the municipality, dashed where drawn between the addresses, numbered from
zoom 14. A click picks the okrsok there as well as the council
constituency, and the ballots name it under the place (`d` in the hash,
`d=3~` from an approximate boundary), as they do for an address found by
the search or clicked, whose okrsok comes with the address files. A
street or part of a municipality chosen in the search is named with its
okrsok where all its houses are in one (which the ballots' okrsok scope
then takes), else with the numbers of its polling districts, and likewise
its council constituency or constituencies (data.js `ballots` `group`).
The 2026 results can colour the map (`js/mapmode.js`): a candidate's share
of the votes by area, from a pin at the end of their row, which also
fits the map to the contest's area: across its areas where it spans
several (a regional contest, or Bratislava's or Košice's city contests by
city district), else over its one area (a mayor's municipality, a
council's municipality or council constituency, in the strongest step,
there being nothing to compare it with); or, from the
boundaries menu once counting has started, the turnout of the municipal
elections (every okres file of the results: each municipality, and
each district of Bratislava and Košice, by its own mayor and council), of
the two cities' own elections of a city mayor and council, on ballots of
their own (the city files; by district where the mayor's contest has
them, else the city alike), or of the regional elections. The units follow
the zoom, as the boundary overlays do, each as fine as its figures go:
below the municipalities' zoom (9.5) each regional constituency as its
municipalities together; from there each municipality by its own figure;
from zoom 11, where the council constituencies' borders begin, those of a
municipality drawn as its constituencies by theirs (a council's own, any
other contest's polling districts summed per constituency, as the
municipal okrsok file's council contests group them: live.js
`okrsokCouncils`, also for the regional contests); from zoom 13, where the
polling districts' borders begin, every polling district drawn (an okrsok
without an area, addressless, is not one) by its own figure from the
final results' okrsok files (`okrsky/<area>.json`, fetched only while
something shows them). A municipality without finer figures keeps its
own at every zoom, and a council constituency's own contest colours its
constituency at every zoom, the municipality having no figure of it.
These thresholds hold whether the overlays are on or not (draw.js
`showsUnits`). Each unit takes one of six steps of a colour (a
candidate's votes the results' green, `--map-result-*`; a turnout the
colour its area is drawn in, mixed into the land: the municipalities'
red, a council constituency's orange, the cities' green, a regional
contest's violet) on one scale over the values of the units of every
level, so that a colour means the same at each zoom, in whole percentage
points (30–50 % where every unit lies between them, not 0–50 %), the
areas not counted yet left out of it and uncoloured; borders and labels
stay above, and each value is a label of its own under the name or number
of its unit, which stays where it was. A legend on the map (under the
search card on phones) names what is shown and the units it is shown by
("by municipalities, council constituencies and polling districts, finer
as you zoom in"), gives the scale and the overall figure, and turns it
off; it all follows the results as they change. Every contest, once
its candidates' votes are in, has a second button before its pin that
colours each unit, at every zoom as above, by the candidate with the
most votes there (for a council of several seats its top candidate, not
those elected, as the legend says), in a colour of each candidate's own
(`--map-series-*`, the eight with the most votes overall, the others in
grey; a tie is left uncoloured), the legend listing them with the number
of the finest units each leads. With a mouse, pointing at the coloured
map names the unit whose colour is under the pointer (a regional
constituency, municipality, council constituency or polling district)
with its figures, and a polling district's turnout in the municipal
elections with its 2022 one where the district is the same as then (not
in the regional ones: a different election). The candidate card shows
under each counted contest where the candidate's votes came from: the
polling districts (else municipalities) with the most of them and those
with the highest share (of the units with at least 30 valid ballots, where
two or more have as many), and a pin that shows the votes on the map. The
selected place, candidate, Favourites
and the About dialog are kept in the URL hash, so links can be shared, and
so are the circled candidates and the filter, though Back and Forward leave
those as they are (`js/app.js`).
The About dialog (`js/about.js`) is a short page with the project's
purpose, the source code, the version (a link to its GitHub release) and
the license, and links to its sections (`#v=about-method`, `-sources`,
`-research`, `-disclaimers`). The site makes no requests to other servers,
the election results included: they are files of the site,
`/results/<election day>/` (the shell's config `results`; `js/live.js`
reads its `status.json` and the files it names, docs/results.md);
`web/_headers` (the base of `dist/_headers`) sets a Content-Security-Policy
whose connect-src is `'self'` alone, so the browser enforces this. Code,
libraries and images are under their versioned directories, kept by
browsers for good, and every JSON file is fetched with `?v=` and the
build's data version (`dataVersion` in the shell's config; `dataUrl` in
`js/files.js`), the results' files with the hash `status.json` gives
them, kept a day, and `status.json` revalidated on every load, so a
release reaches visitors on their next page load (`build.py`, "Cache
busting").
