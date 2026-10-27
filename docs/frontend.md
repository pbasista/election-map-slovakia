# The frontend

`web/` holds the frontend:
ES modules with no build step, Preact + htm for the components
and Leaflet for the map view.
`ems build` copies it into `dist/` under versioned paths
([pipeline.md](pipeline.md#build)).
The whole page is the map;
a pane beside it (a bottom sheet on phones) shows the ballots of a place.

## Files

| In `web/` | In `dist/` | What |
|---|---|---|
| `app.css`, `js/` | `/assets/<v>/` | the styles and the ES modules |
| `vendor/` | `/assets/vendor/<vv>/` | Leaflet 1.9.4, Preact + htm, the QR code generator |
| `img/` | `/assets/img/<iv>/` | party logos |
| `cache.css` | `/assets/` | the stylesheet of the cached copies |
| `index.html` | `/<lang>/` | the app shell, a template |
| `picker.html` | `/` | the root page that picks the language, a template |
| `i18n/<lang>.json` | | the hand-written UI strings, Slovak and English |
| `_headers` | `/_headers` | the base of the response headers |

Each version (`<v>`, `<vv>`, `<iv>`) is a hash of its tree.

- **Vendored libraries.**
  Leaflet is its `dist/leaflet.js` less the source-map comment,
  since the map is not shipped.
  The modules import the libraries as `'../vendor/…'`,
  so `web/` runs as it is;
  the build rewrites that prefix to `/assets/vendor/<vv>/`
  in the modules directly in `js/`, where it means `web/vendor/`.
- **UI strings.**
  The build adds the other languages' and the occupations' translations
  ([agent-jobs.md](agent-jobs.md#translation)).
  The card and the tooltip of a translated occupation give the Slovak original;
  party names stay as the official lists write them.
- **Search engines.**
  `app.description` is the search engines' description of a page.
  `app.features`, what the site offers in a paragraph,
  is on the root page in each fallback language
  and in an app shell's `<noscript>`,
  for search engines that do not run the page's scripts.

## Layout

The site name with the search floats on the map,
with round buttons for language, the map's layers, light/dark theme
and Favourites, zoom, and help
(the disclaimer, and from there the About dialog).

- **Popovers.**
  A button's menu is a non-modal dialog beside it
  (`js/controls.js` `Popover`):
  it takes the focus, and Esc, a click elsewhere or the focus leaving it
  closes it, Esc returning the focus to the button;
  one is open at a time (app.js `menu`).
  It is never taller than the screen (scrolling inside past that)
  nor wider than the room left of the buttons,
  and moves up beside its button as far as it would otherwise run
  off the bottom of the screen
  (in the lower column, down off the top).
- **Map layers.**
  Three buttons in one pill, a group named "Map layers"
  (`LayerMenus`), each with its own short menu:
  the constituency overlays
  (regional councils, Bratislava and Košice, municipal councils,
  polling districts),
  with when each appears and the legend of those on
  folded under "What the lines mean";
  once counting has started, the 2026 turnout on the map
  (none, or that of one election),
  the button dotted while one is shown;
  and the base map:
  roads, railways and water, and buildings.
  The overlays and the base map's layers are all on when the page opens.
- **Phones.**
  With the sheet open, the buttons above the zoom
  go under one ⋮ button that puts them out in their column.
- **Status line.**
  While the polls are open (site.toml `polls_open`, `polls_close`),
  a line under the site name says the voting is under way,
  with a still bar of how much of the voting day has passed.
  After they close, while nothing is counted yet
  (status phase `none`, or no results to read yet)
  and the results are still polled,
  it says that the results are awaited and will appear as they come in.
  Once counting starts, the count's status takes its place
  (`js/live.js` `LiveStatus`):
  how far each election has got
  by the registered voters whose polling districts are counted.
- **Pane.**
  Clicking a place or a search result opens a pane with the ballots there
  (a bottom sheet on phones).
  It closes with its button, Esc or, on phones, a swipe down.
- **Theme.**
  The theme follows the device unless chosen in the theme menu
  (kept in localStorage);
  `js/theme.js` applies it before the first paint.

## Ballots

### Contest header

A contest's header shows whether it is open:
tinted when open;
muted, with a grey bar at its side for the candidates it hides, when closed.
Its tooltip says what a press does.

At its end a short horizontal meter (`Turnout` in `js/ballots.js`)
gives the turnout of the last election in the contest's area,
the share and the year above it,
without making the header taller; the tooltip gives the numbers.
The last election is 2022, or a municipal by-election since:

- a council's, where it now has several constituencies:
  of the polling districts that make up the constituency
  where they are known and the same as then,
  else of the whole municipality,
  the 2022 constituencies being drawn otherwise;
- a regional constituency's: summed over its municipalities.

Once the contest is counted,
the meter shows the 2026 turnout in the results' green,
the last election's as a grey tick on the track with its figures under it.

### Results on the ballots

- **Night note.**
  Where a contest is counted but its candidates' votes are not there yet
  (on election night a municipality's turnout, its winners at most,
  until ŠÚ SR publishes the candidates' votes;
  or a count with the turnout alone),
  a note above its candidates says so in words
  (`nightNote` in `js/ballots.js`).
- **Seats line.**
  On a partial count of a council (`oz`, `zsk`),
  the first `seats` candidates by votes,
  those who would win a seat so far,
  have their numbers in the results' green,
  and a dashed green line labelled "↑ seats: N" follows the last of them
  where a candidate who would not comes next
  (`seatPlaces`; a screen reader hears each one's place,
  the label's tooltip explains it).
  Not once it is final: then its elected are marked.
- **Unit choice.**
  Where the place lies in units of the contest's area
  with figures of their own in the final results
  (live.js `placeResults`),
  a compact choice under the header
  ("Whole contest | <municipality> | Constituency No. k | Polling district No. n",
  only those that differ from the whole and from each other)
  switches the candidates' votes, shares and bars and the turnout meter
  to that unit.
  The units are:
  - the municipality or city district
    of a regional or Bratislava's or Košice's city contest,
    from its `areas` entry;
  - the council constituency of a municipality split into several,
    its polling districts summed,
    for any contest but that constituency's own council;
  - the polling district of an address or a map pick.

  The turnout meter of a unit shows its 2022 municipal turnout
  in a municipal contest where the polling district is the same as then;
  none for the other units.
  The choice is one for every contest of the ballots,
  kept while browsing places:
  a contest without the unit chosen shows the finest it has
  that is not finer.
  It starts at the whole contest.

### Circling and crossing out

A candidate's ballot number circles the candidate (`js/picks.js`),
as voters circle numbers on the ballot.
A contest lists its circled candidates even when closed,
the filter never mutes them,
and its header counts them,
flagging the number of seats when more are circled than are elected
(which on the ballot itself would make it invalid).

Every button on a row has an alternate press:
Shift+click, or a double click or tap
(the only one a phone has; `useRowActions` in `js/ballots.js`).

- On the number it crosses the candidate out with a red cross,
  which the filter then mutes like any it excludes
  (the filter bar counts them, and clearing it clears them).
- On a party tag or a mark it adds the party or mark to the filter
  with its candidates hidden,
  where a plain press shows only them.
- Each press, repeated, undoes itself.

With Shift held, the button under the pointer previews the alternate press:
a faint cross on a number, a faint dashed ring on a party tag or mark
(the root element has the class `shift`).

### Candidate card

On a candidate card each of the candidate's contests starts closed,
showing just the candidate (and those circled).
Its header opens it to the others,
whom the filter applies to
(never to the candidate, who stays first).

Its pin, in the colour the area is drawn in on the map,
shows the area on the map while the card stays open:
the municipality, city district, constituency or,
in Bratislava and Košice, the city or its council constituency,
or for a regional contest
the self-governing region or its regional constituency.

Under each counted contest the card shows
where the candidate's votes came from:
the polling districts (else municipalities) with the most of them
and those with the highest share
(of the units with at least 30 valid ballots, where two or more have as many),
and a pin that shows the votes on the map.

### Contest pins

On the ballots of a place and in Favourites,
the same pin fits the map to the contest's area
and highlights it in its colour beside the place.
The place stays selected, its ballots and the list as they are,
until another place is
(`fitArea` in `js/map.js`, draw.js `showArea`).

Once the contest is counted,
the pin's next press colours that area by the contest's 2026 turnout,
in the colour the area is drawn in
(the pin filled with it while it does),
and another takes it off (`ContestMapButton` in `js/mapmode.js`).
While the map shows another of the contest's results,
its first press does so at once.

The map is fitted to a contest's area
when the results shown become that contest's
(from none, a turnout layer or another contest),
not when they switch between its candidates, its turnout
and who got the most votes,
nor as zooming changes their units:
the view the visitor zoomed to stays.

## Favourites

Favourites (`js/favourites.js`) lists every circled candidate's contest
the same way, the circled first.
Buttons by its title copy a link to them and the filter alone,
with the list open,
or show that link as a large QR code in a dialog of its own,
for another device's camera
(the encoder, `vendor/qrcode-generator.module.js`, loads on first use).

It opens only with its button:

- **From 960 px wide**, as a pane of its own beside the first,
  as the search results are, as wide as the page allows.
  A candidate chosen opens in the first pane,
  and a map click or a contest's pin keeps the list open,
  but a place found by the search closes it, as it would hide that place.
- **Narrower**, it is what the pane shows,
  as wide as the page allows on a tablet;
  a phone's sheet leaves the place in view above the list.

## The map

### Drawing

The map uses Leaflet for the view, without any tile layer,
and one canvas of its own,
drawn in a worker (`js/render.js` running `js/draw.js`)
so that fetching, decoding and drawing never hold up the page's main thread:
it only moves and scales the canvas with the gesture
and swaps in each finished drawing.

- **Geometry.**
  The background is our own geometry,
  loaded per okres and level of detail as the view changes
  and kept as typed arrays in a cache bounded by size (`js/topo.js`),
  with labels and, from zoom 16, house numbers,
  all in the theme's colours.
- **Neighbours.**
  The countries around Slovakia are drawn below it, duller,
  with dashed borders and their names where most of each shows.
  They cannot be clicked,
  and the lowest zoom keeps every view within them.
- **Borders.**
  Areas are only filled;
  every border is stroked once from the topology,
  in the style of the highest boundary it is part of.
  A dashed one is cut into its dashes only where the drawing shows it
  (the canvas would dash it whole, far beyond the view when zoomed in).
- **Zoom** is continuous (`js/zoom.js`):
  wheel, trackpad, pinch, buttons and double-click
  scale the canvas every frame.
  While a pan or zoom goes on,
  the view is drawn again at a lower resolution
  whenever the last drawing no longer covers it,
  and sharp once the gesture settles;
  what has not loaded yet is added as it comes.

### Base map

A faint base map helps find a neighbourhood
(`base/`, built by `ems basemap` from OpenStreetMap,
no tiles from other servers):
rivers, larger streams, lakes and reservoirs,
roads by class and railways,
and from zoom 16 the buildings.
The base map menu switches the lines and waters off
("Roads, railways and water features"),
and the buildings apart ("Buildings").

- **Loading.**
  The lines and waters load with the shards
  (a file per okres at their level of detail, cached like them;
  `base/coarse.json`, motorways, major rivers and lakes,
  with the coarse view).
  The buildings load from the zoom in `base/index.json` `buildings` (16)
  for the obce whose shards reach into the view
  (`base/obec/<code>.json`, as the address files),
  cached by their vertices;
  an obec's file is one path per cell of about 400 m,
  so that a drawing fills only the cells in view.
  Below zoom 16 they would more than double the time of a drawing
  in a city centre.
- **Drawing.**
  Draw.js (`drawBase`) draws it over the land and the results' fills
  and below every border, highlight and label,
  at the theme's `--map-base-alpha` (0.5 light, 0.6 dark),
  in the theme's `--map-base-*` colours:
  the waters, the buildings, the waterways, the roads, the railways,
  from paths made once per bin (a cell for the buildings) and class
  and scaled by the transform.
  (Drawn opaque on a canvas of its own and laid on at the alpha,
  a road's casing would not show faintly under its fill,
  but that cost 2.5 ms of a drawing of 30 and hardly shows.)
- **Roads and railways** are drawn as on the web maps people know,
  so that they never pass for a border
  (the borders are thin cool greys and colours):
  - a road at least 2.2 px wide is a band,
    a casing in its colour with a light fill inside
    (white or light grey for the minor and tertiary roads,
    yellow for the primary and secondary roads,
    orange for the motorways and expressways);
    all the casings are drawn before all the fills,
    so roads join without seams;
  - a narrower road is one warm line in its casing colour,
    lighter and warmer than the cool grey obec border;
  - a railway is a dark line with ticks across it,
    from zoom 11 (`BASE_RAILS`; the ticks are made for each drawing,
    as the dashed borders);
    a tram is thinner and lighter, with ticks from zoom 14.
- **Line widths** grow with the zoom by class
  (`BASE_WATERWAYS`, `BASE_ROADS`, `BASE_RAILS`):

  | From zoom | Classes |
  |---|---|
  | lowest | motorways, expressways, rivers |
  | 9 | primary and secondary roads, railways, canals |
  | 12 | tertiary roads, trams, streams |
  | 13 | minor streets (their mesh greys the towns below that) |

  Below zoom 16 the dense classes
  (minor and tertiary streets, streams, railways)
  are hairlines of one canvas pixel:
  stroked wider, they took most of a drawing's time in a city.
  So the minor and tertiary streets become bands only from zoom 16,
  the major roads from zoom 12 to 14.

### Polling districts

The okrsky (polling districts) of the municipalities whose okrsky are known
are an overlay of their own in the constituencies menu
(`geo/okrsky/<okres>/<lod>.json`, from zoom 13):
thin blue lines inside the municipality,
dashed where drawn between the addresses,
numbered from zoom 14.

- A click picks the okrsok there as well as the council constituency,
  and the ballots name it under the place
  (`d` in the hash, `d=3~` from an approximate boundary).
  So they do for an address found by the search or clicked,
  whose okrsok comes with the address files.
- A street or part of a municipality chosen in the search
  is named with its okrsok where all its houses are in one
  (which the ballots' okrsok scope then takes),
  else with the numbers of its polling districts,
  and likewise its council constituency or constituencies
  (data.js `ballots` `group`).

### Results on the map

The 2026 results can colour the map (`js/mapmode.js`).
What it shows:

- **A candidate's share** of the votes by area,
  from a pin at the end of their row,
  which also fits the map to the contest's area:
  across its areas where it spans several
  (a regional contest,
  or Bratislava's or Košice's city contests by city district),
  else over its one area
  (a mayor's municipality,
  a council's municipality or council constituency,
  in the strongest step, there being nothing to compare it with).
- **The turnout**, from the turnout menu once counting has started:
  - of the municipal elections
    (every okres file of the results: each municipality,
    and each district of Bratislava and Košice,
    by its own mayor and council);
  - of the two cities' own elections of a city mayor and council,
    on ballots of their own
    (the city files; by district where the mayor's contest has them,
    else the city alike);
  - or of the regional elections.
- **The leader.**
  Every contest, once its candidates' votes are in,
  has a second button before its pin
  that colours each unit by the candidate with the most votes there
  (for a council of several seats its top candidate, not those elected,
  as the legend says),
  in a colour of each candidate's own
  (`--map-series-*`, the eight with the most votes overall,
  the others in grey; a tie is left uncoloured).
  The legend lists them with the number of the finest units each leads.

**Units by zoom.**
The units follow the zoom, as the boundary overlays do,
each as fine as its figures go:

| Zoom | Units |
|---|---|
| below 9.5 (the municipalities' zoom) | each regional constituency, as its municipalities together |
| from 9.5 | each municipality by its own figure |
| from 11, where the council constituencies' borders begin | a municipality's council constituencies by theirs |
| from 13, where the polling districts' borders begin | every polling district by its own figure |

- A council constituency's figure is the council's own,
  or for any other contest its polling districts summed per constituency,
  as the municipal okrsok file's council contests group them
  (live.js `okrsokCouncils`, also for the regional contests).
- Polling districts come from the final results' okrsok files
  (`okrsky/<area>.json`, fetched only while something shows them);
  an okrsok without an area (addressless) is not one.
- A municipality without finer figures keeps its own at every zoom,
  and a council constituency's own contest colours its constituency
  at every zoom, the municipality having no figure of it.
- These thresholds hold whether the overlays are on or not
  (draw.js `showsUnits`).

**Colours.**
Each unit takes one of six steps of a colour:
a candidate's votes the results' green (`--map-result-*`);
a turnout the colour its area is drawn in, mixed into the land:
the municipalities' red, a council constituency's orange,
the cities' green, a regional contest's violet.
The steps are one scale over the values of the units of every level,
so that a colour means the same at each zoom,
in whole percentage points
(30–50 % where every unit lies between them, not 0–50 %).
The areas not counted yet are left out of it and uncoloured.
Borders and labels stay above,
and each value is a label of its own
under the name or number of its unit, which stays where it was.

**Legend.**
A legend on the map (under the search card on phones)
names what is shown and the units it is shown by
("by municipalities, council constituencies and polling districts,
finer as you zoom in"),
gives the scale and the overall figure, and turns it off;
it all follows the results as they change.

**Pointing.**
With a mouse, pointing at the coloured map names the unit
whose colour is under the pointer
(a regional constituency, municipality, council constituency
or polling district) with its figures,
and a polling district's turnout in the municipal elections
with its 2022 one where the district is the same as then
(not in the regional ones: a different election).

## The URL hash

The selected place, candidate, Favourites and the About dialog
are kept in the URL hash, so links can be shared.
So are the circled candidates and the filter,
though Back and Forward leave those as they are (`js/app.js`).
Examples are in [testing.md](testing.md#the-site-locally-with-results).

## About dialog

The About dialog (`js/about.js`) is a short page
with the project's purpose, the source code,
the version (a link to its GitHub release) and the licence,
and links to its sections
(`#v=about-method`, `-sources`, `-research`, `-disclaimers`).

## Results and caching

The site makes no requests to other servers, the election results included:
they are files of the site, `/results/<election day>/`
(the shell's config `results`;
`js/live.js` reads its `status.json` and the files it names,
[results.md](results.md)).
`web/_headers` (the base of `dist/_headers`)
sets a Content-Security-Policy whose connect-src is `'self'` alone,
so the browser enforces this.

Code, libraries and images are under their versioned directories,
kept by browsers for good.
Every JSON file is fetched with `?v=` and the build's data version
(`dataVersion` in the shell's config; `dataUrl` in `js/files.js`),
the results' files with the hash `status.json` gives them, kept a day,
and `status.json` revalidated on every load.
So a release reaches visitors on their next page load
(`build.py`, "Cache busting";
[deploy.md](deploy.md#caching)).
