# Changelog

Notable changes, newest first. The version is set in
`src/election_map_slovakia/__init__.py`; tagging `vX.Y.Z` builds and deploys
it (see [docs/deploy.md](docs/deploy.md)).

## 0.8.5 — 2026-10-30

- **The app reads the deployed manifests with the project's User-Agent.**
  `*.pages.dev` turns Python's own away (403, Cloudflare's error 1010),
  so `ems build --deployed` stopped at the first manifest and 0.8.4's
  release deployed the data parts but not the app.
  `scripts/pages_trial.py` sends it as well.

## 0.8.4 — 2026-10-29

- **The release reads the secrets of the `production` environment.**
  The Cloudflare token and account are secrets of that environment,
  which reach only the jobs that name it: the app's did, the new jobs
  that ask which data parts are deployed and deploy them did not, so
  0.8.3's release stopped at the first with no credentials. Both name
  `production` now.

## 0.8.3 — 2026-10-29

- **Data keys from the code's source text.** 0.8.2 still counted the
  code by its syntax tree, and the tree differs even between releases of
  one Python: 3.12.3, which GitHub's runners have, writes an f-string's
  format spec with an empty piece more than 3.12.12, so the lock failed
  `ems data lock --check` on the 3.12 runner and 0.8.2 was not released.
  The keys now count the code's text as it is, comments included, which
  no Python reads differently; only the CLI's part of the map steps is
  found by the parser, its lines then taken as they are.

## 0.8.2 — 2026-10-29

- **The same data keys on every Python.** The keys counted the code by
  the text `ast.dump` gives of its syntax tree, which differs between
  Python versions (3.12 adds an empty `type_params` to every function
  and class, 3.13 leaves out fields at their defaults): the lock written
  with Python 3.11 failed `ems data lock --check` on 3.12 and 3.14, so
  0.8.1 was not released. The tree is now written out field by field,
  unset fields left out, giving the same keys on 3.11 to 3.14.

## 0.8.1 — 2026-10-29

- **The checks pass on Python 3.11.** With Python 3.11's numpy, ty took
  the address points of a unit kept on the map (`geo.py`) for numpy's
  `SupportsIndex`, so the 0.8.0 commit failed the Python 3.11 checks and
  0.8.0 was not released; 0.8.1 is that release with the point chosen
  before the assignment. The map is the same.

## 0.8.0 — 2026-10-29

- **Party logos of each election's own time.**
  A party's logo in `config/parties.toml` is now given per election
  (`[party."…".logo.<slug>]`), as it was at that election, and each
  election's pages and About credit their own. The 2022 pages no longer
  show the 2026 logos: their logos were checked against the parties'
  sites as the Internet Archive kept them in autumn 2022 and the version
  histories of the Commons files. SaS shows its green and blue letters of
  2022 instead of the navy logo of 2024; SPOLU, Dobrá voľba, NOVA,
  Kresťanská únia, Národná koalícia, PRINCÍP and Team Bratislava get the
  logos they used then; KDH and the Aliancia, under their 2022 names, the
  logos they still use; the others whose design is unchanged keep it.
  Parties without a freely licensed copy of their 2022 logo (SNS, Sme
  rodina, SHO and others), or whose 2022 logo is not known, are shown by
  their short form.
- **The site deployed in parts; data only when it changes.**
  The app (page shells, code, styles, UI strings) is now one Cloudflare
  Pages project, and each election's map another (`ems-map-<slug>`: map,
  base map, addresses) and its data a third (`ems-data-<slug>`:
  candidates, research and the occupations' translations), as are the
  cached copies of cited pages (`ems-sources`, at
  `sources.volebnamapa.sk`) and the results (`ems-results`, at
  `results.volebnamapa.sk`). `ems build` writes them to `dist/app/`,
  `dist/map/<slug>/`, `dist/data/<slug>/`, `dist/sources/` and
  `dist/results/`, each with its own `_headers`, `404.html` and file
  budget; `ems serve` serves them as one site. Every data part has a key,
  a digest of everything in the repository its content depends on
  (pinned inputs, configuration, curated data, the code that makes the
  data and its libraries), computed without building; `ems data lock`
  writes the keys to `data/published.toml`, which CI checks on every
  push. An election's map depends on that election alone, so new
  research, corrected links or translations leave the maps, by far the
  largest part, deployed and in visitors' browsers. A release deploys a
  data part only when its key is not deployed yet (`ems data status`,
  `ems data deploy`), and otherwise builds and deploys the app alone, in a
  few minutes, for the data deployed (`ems build --deployed`): the app
  names each election's bundles by the addresses of the deployments that
  carry their keys, so data never change under an open page and a rolled
  back app brings back its data. On an election night `ems results
  deploy` deploys the results part alone, which a release with the same
  key leaves in place. The GitHub release carries the app's files only.
  `scripts/pages_trial.py` tries out on a throwaway project what this
  relies on (docs/deploy.md). Locally these commands use the login of
  `npx wrangler login`, or `CLOUDFLARE_API_TOKEN` and
  `CLOUDFLARE_ACCOUNT_ID` where set, as CI does.
- **Every input pinned and kept in the input store.**
  Every input of `config/inputs.toml` is pinned by its sha256 and the day
  the pinned file was retrieved, which About now shows. The pinned files
  are kept, unchanged, as assets `<sha256>-<file>` of the pre-release
  `inputs` of the project's repository: `ems fetch` takes a pinned
  file from `data/raw/` where it is there (recorded in its manifest, or
  with the pinned digest), else from the store, else from
  its source. `ems inputs update` pins what a source serves now and `ems
  inputs publish` uploads the files the store lacks; `data/fallback/` is
  gone.
- **Several elections: 2022 beside 2026.**
  The site shows the municipal and regional elections of 29 October 2022
  beside those of 24 October 2026, each on pages of its own
  (`/<lang>/2022/`; `/<lang>/` stays the latest). The logo in the search
  card opens the list of elections, grouped under a heading per kind of
  election, one line each; switching keeps the language, the map view,
  the place and, where the person is linked, the open candidate.
  The 2022 pages have their own candidates and final results (Statistical
  Office packages), down to the polling district; Krušovce, which has no
  2022 result, says so, and the office holders before 2022 are not shown,
  which the ballots and About say. Their map is drawn on the 2026
  boundaries, naming the 16 municipalities whose boundary moved since
  January 2022 on their ballots, in the map's credits and in About, with
  the address register of 09/2022 and an OpenStreetMap base map of
  1 January 2022. Council constituencies and polling districts are
  transcribed from the 2022 municipal documents; a document that states
  no date is used where an Internet Archive capture or a posting before
  the elections bounds it, or it names them, and the ballots and the map
  say its date is uncertain; where a 2022 document does not place every
  address (hamlets it names that the register keeps elsewhere, houses it
  leaves out, a split it leaves unclear), a later source fills it in (the
  2026 rules, the 2023 referendum's or another later document), and the
  ballots and the map say part of the borders comes from it; where none
  was found, the 2026 rules stand in only if the layout provably matches,
  and the ballots say so; where no 2022 document places the addresses at
  all, Divina's constituencies and Veľký Meder's polling districts are
  drawn with the 2026 borders, which the ballots, the map and About call
  indicative only; otherwise every constituency is listed with the notice
  that the 2022 borders are not known, and where polling districts are
  not drawn, that the results by polling district cannot be placed on the
  map. On a 2022 page About has a section "What comes from 2026" listing
  every substitution and gap with counts, and lists only that election's
  sources. Candidates of both elections are linked by municipality or
  region, name and age: a 2026 candidate who stood for the same office in
  2022 has a grey clock beside the chair that unfolds the 2022 result,
  the card lists a person's candidacies in the other election, and a 2022
  candidate is shown the 2026 research cut to the findings published
  before 29 October 2022 (undated ones left out and counted). The 2026
  pages show the 2022 figures on the 2026 polling districts, constituencies
  and municipalities, saying how each was found (same district, same
  number with about as many voters, estimated from addresses, not known),
  in tooltips, contest headers and a 2022 option on candidate maps. Office
  holders are those "at the time of the election; later changes are not
  known", and the texts name the page's year. The occupations the 2022
  lists add are translated into every language like 2026's. Behind it,
  the elections are listed in `config/elections.toml` with the inputs
  their steps read;
  the steps run per election (`--election`), writing `data/build/<day>/`,
  and `ems check` checks each election's files.
  Research jobs, `ems results poll` and `ems results fake` are of the
  latest election only; the UI strings are fetched once for every
  election's page.

## 0.7.0 — 2026-10-28

- **Candidate card notices in one line.**
  The word on serious controversies under a candidate's name, and the
  note that the research is written by AI, are each a line now, like the
  notices of the council ballots: "Serious controversies found: 2" in
  red, "Written by AI: it may be wrong" in amber, the whole text unfolded
  under them on a press. The jump to the controversies is an icon button
  on the red line, beside its summary rather than in it, as a summary is
  itself a button. The controversies' text is reworded so that its last
  line is not the number alone, as it was in Slovak and Czech. The
  summaries are cut to what a 360 px phone shows in every language
  (`translate.py` limits). The Slovak and Czech description of the site
  speaks of the candidates' "kontroverzie" / "kontroverze", as the rest of
  the site does, rather than "kauzy", which suggests a case on its way to
  court.
- **A faster map.**
  A drawing of the whole country takes 23 ms instead of 31 (headless Chromium,
  1440 × 900), and 13 ms instead of 30 on a phone; the results by
  municipality over the country 23 ms instead of 32 to 37, Košice at
  street level 18 instead of 22. Each vertex now has the zoom level from
  which it is drawn, and the lower levels leave out those that would fall
  within a third of a pixel of the line (`topo.js` `levels`); the dashed
  borders are cut into square-ended dashes, which rasterize at half the
  cost of round caps; an obec or okres border under a regional or city
  obvod border is no longer stroked beneath it; and the end of a pan no
  longer asks for a drawing of the view just drawn. Over a tour of the
  map that made 15 % fewer drawings and 27 % less drawing time.
- **Turning on a turnout map no longer holds up the page.**
  Each of the some 230 results files the municipal turnout loads rendered
  the page again and worked out the map's figures anew: two seconds of
  the page not answering. The files that come together are now taken
  together (`live.js`), and the figures look each okrsok's council obvod
  up once: the page is busy for 0.1 s.
- **Lighter map indexes.**
  `geo/index.json` and `base/index.json`, which every visit loads first,
  listed the size of every geometry and base map file for `ems check`
  alone: 24 KB of the 37 KB they take gzipped. They no longer do;
  `check` compares the base map files there are with those the index
  lets the app request.
- **A faster `make`.**
  `ems make --force` takes 1 min 54 s instead of 2 min 39 s (8 CPUs),
  and an up-to-date `make` 13 s instead of 25, its output byte for byte
  the same.
  The gzip sizes in the summaries are kept by content
  (`data/build/gzip-sizes/`), so that only new files are compressed:
  9 s of every build, 5 s of `basemap`.
  The obce are cut the costliest first, so that no worker is left with a
  city when the others are done, and with one overlay fewer each;
  the levels of detail of the shards and of the okrsky are cut into arcs
  and checked side by side, and the borders of the okrsky reaching beyond
  their obvod are simplified in the workers; `addresses` assigns the
  obvody and okrsky of the obce in workers too.
  `build` reads the data files it hashes, and `dist/` for its summary, in
  threads; `check` starts the base map, its longest part, first.
- **Contests in one order.**
  A candidate card listed a person's candidacies in the order of their ids,
  so a regional president came before a mayor,
  unlike a place's ballots.
  Both now go from the most local:
  the municipality's or city district's, then Bratislava's or Košice's,
  then the region's, of one area the council before the mayor or president.
- **Results on the map from a contest's header, one button each.**
  The pin by a contest's name showed its area on the map,
  and only pressed a second time its 2026 turnout,
  which nobody would guess without reading its tooltip.
  Now the turnout meter in the header is itself the button
  that puts the contest's turnout on the map,
  with the ballot box of the turnout menu beside the figure,
  and before it a button with a folded map shows who got the most votes where;
  both are outlined like buttons and tinted while the map shows theirs.
  Showing a contest's area alone is gone, as either result shows it
  (the map fits to the area), and with it the area links (`r=`).
  A candidate's votes on the map have the folded map too:
  a pin now stands only for a place.
- **Contest headers without ragged breaks.**
  The turnout and two buttons beside the contest's name
  left it so little room that most names broke over two or three lines.
  Now the name takes a line of its own across the header,
  with the seats, candidates and votes under it
  and the buttons beside those, in one column down the list:
  a header is three lines, not four, and they line up.
  A press anywhere in the header but its buttons opens or closes it.
- **Ties on the winner map.**
  A unit where several candidates tied for the most votes
  was left blank, as if there were no figures
  (in the final results 371 polling districts and 98 larger units).
  Now it is striped in the colours of all those tied
  and labelled with all their surnames;
  its tooltip, the legend and the overall figure name the tie,
  and the legend counts the tied units.
- **Shorter notes on the ballots.**
  The note above a council's contests
  (all its constituencies listed, boundaries approximate or estimated)
  is one line of summary, its whole text in the tooltip and a press away;
  the documents that set the constituencies are one line too,
  several of them numbered, each title in its tooltip.
- **Base map icons that say what they show.**
  The base map's button and its menu had a wave crossed by a line
  and tilted squares.
  Now the button is a house and a tree beside a road;
  in the menu the roads, railways and water are a road, a railway
  and a wave as the map draws them, and the buildings two houses.
- **Links that open the same view.**
  A link carried the place, the candidate and the circles,
  but not what the map showed.
  Now the address also keeps the map's view (`m=zoom/lat/lon`),
  the layers switched off (`h`)
  and the results on the map (`mr`: a turnout,
  who got the most votes where, or a candidate's votes),
  so that a shared link opens on the same map;
  Back and Forward leave them as they are, as they do the circles.
- **Lakes not coloured by the results.**
  The faint lakes took on the colour of the results under them,
  a bluish shade that read as another value or candidate.
  While results are shown, the lakes are now opaque
  in their usual colour, and the colours stop at the shore;
  the borders still cross a lake, and a click in one still picks its unit.
- **Every constituency document named.**
  The documents of Bratislava's and Košice's councils
  and of the eight regional councils were linked as "official document".
  Each now has its title and designation (resolution and date),
  and a constituency list without a title fails to load.

## 0.6.0 — 2026-10-27

- **Buildings on the map.**
  From zoom 16 the base map draws the buildings of OpenStreetMap,
  so that a place can be found by the houses around it,
  under the house numbers and every border.
  `ems basemap` writes them per municipality
  (`base/obec/<obec>.json`, 2.6 million buildings, 82 MiB, 26 MiB gzipped),
  and the app loads those of the municipalities in view.
  The base map menu switches them off on their own.
- **Roads and railways unlike borders.**
  Roads were thin grey lines like the municipality borders.
  Now a wide road is a light band in a casing,
  the major ones yellow and the motorways orange,
  and a railway is a dark line with ticks across it,
  as on the web maps people know; the borders are as they were.
- **The layers menu in three.**
  One button showed the constituencies, the base map and the turnout,
  with the zoom note and the legend, taller than a phone's screen.
  Now three buttons in one group open short menus of their own:
  the constituencies (the zoom note and the legend
  folded under "What the lines mean"),
  the 2026 turnout (the button dotted while one is shown)
  and the base map.
  Every menu stays on the screen, scrolling inside if it must.
- **The map on a phone.** The sheet with a place's ballots or a
  candidate card stops at three heights: lowered to its first row, half
  the screen (where a place opens) and up to the search card; it follows
  a drag from its grip, or from the content scrolled to the top, and
  settles at the nearest height or the next one a flick goes to, a drag
  down from the lowest closing it as before; its grip is a button that
  steps through them. Results put on the map from the sheet lower it, so
  the map shows them before it fits them; their legend is then a bar at
  the top of the sheet (the title, the overall figure, the scale or the
  candidates who lead as a row of chips, the units sentence on demand),
  and without the sheet a pill under the search card ("Turnout 48.5 %",
  "Vallo 64.4 %") that unfolds into the whole legend. On a touch screen
  a tap on the coloured map shows that area's figures in a card, with a
  button to its ballots, rather than picking the place. The map's
  credits, shown in full as the map loads, fold into an ⓘ button after
  the first touch of the map or five seconds, as OSMF's attribution
  guidelines allow; the language, map layer, appearance and Favourites
  buttons go under one "more" button while the sheet is open. Wherever
  the panes and the legend would leave a place less than 160 px to be
  fitted into, they give way (the legend first), rather than the map
  zooming out to the country. Wider screens are as they were.
- **Polling district numbers where the districts are drawn.**
  A polling district's number was placed in its area as drawn
  from the address points, which can hold a piece
  that the map draws in another constituency
  (a stray: a house far from the rest of its street).
  The number then stood in another district, without a border:
  in Michalovce, okrsok 7 showed in constituency 6's eastern part,
  around one house of Užhorodská.
  The numbers now go in the districts as drawn;
  10 of the 3,278 were elsewhere.
- **A name or number once in each part of its area.**
  An area seen only in part, its label's own spot out of view,
  had its label slid to wherever its visible part had the most room,
  even into one of its other parts that bore a label of its own:
  "No. 6" stood twice in each of the two smaller of Michalovce's
  constituency 6, once by the polling district's number
  and once by the municipality's name.
  Where another part is labelled in view, the label now stays in its own
  part; a council constituency's or a municipality's result
  goes under the first of its labels drawn.
- **Panning right after a pinch.**
  On a phone, a pan begun within a quarter of a second of a pinch zoom
  did nothing:
  Leaflet ignores a drag while it "animates" the end of a pinch,
  and with continuous zoom that animation goes nowhere,
  so it lasted its full 250 ms fallback.
  Such an animation now ends at once (zoom.js `dragAfterPinch`).
- **A faster build.**
  `ems make --force` takes 1 min 53 s instead of 4 min 59 s (8 CPUs),
  its output byte for byte the same.
  `geo`, `basemap` and `check` run their independent pieces
  in worker processes (`parallel.py`).
  `geo` loads and assigns each obec's addresses once, not twice,
  and finds the nearest okrsok and the shared Voronoi edges
  without measuring every polygon or sorting rows as records;
  `addresses` reuses the council obvody it has just assigned;
  `basemap` hands libosmium only the ways it draws
  and assembles only the water areas.
  The test that the curated rule sets load
  loaded them all once per file: the tests take 13 s, not 3 minutes.
- **Code and documentation review.**
  The pipeline and the app are refactored for readability
  (long functions split, repetition pulled into helpers,
  clearer names and comments), with outputs byte-identical.
  The README and the docs are restructured into short,
  scannable sections with semantic line breaks.
  NOTICE now also lists qrcode-generator, the ŠÚ SR results,
  the 2026 okrsky list and the party logos,
  and says that Leaflet ships without its source-map comment.
  Okrsok-rules job items name a city district's city
  rather than its code.

## 0.5.0 — 2026-10-26

- **Withdrawn candidates set apart; no "final results" statements.** A
  candidate who withdrew but stayed on the ballot has a grey badge with a
  door after the name (its tooltip says what it means), their share and
  bar in grey, and comes last in the list. The results' status line under
  the title and a contest's "2026: final results" are gone, final going
  without saying now; a contest gives its valid votes. The page
  description and the text for search engines and visitors without
  JavaScript now lead with the results, by constituency, municipality and
  polling district. The base map's label names its water by the
  cartographic term ("water features", Slovak and Czech "vodstvo",
  Polish and Ukrainian "hydrography" and so on) instead of "waters",
  which in several languages meant lakes or bodies of water alone. A page
  loaded after the polls closed no longer flashes "results awaited"
  before status.json is read; it says so only once that has been tried
  and found nothing counted. Polling is off in this release (site.toml
  `live = false`): the final results are in the site, so the app reads
  them once per page load instead of every minute; the polling stays, to
  be turned on again for the next election night.
- **City okrsky and withdrawn candidates in the results.** Bratislava's
  and Košice's own contests put the votes of okrsky sharing a number in a
  council obvod (a number per district) in the right okrsok: by the shares
  ŠÚ SR gives each vote row (a mayor's of the okrsok's valid ballots, a
  council's of its votes together), not by the order of the rows, which
  differs per candidate and had summed the votes of different okrsky into one
  (Luník IX's mayor shares adding up to well over 100 %, the districts'
  figures wrong). Okrsky whose votes still fit more than one way are left
  out of the okrsok files, and so are the districts' figures they make
  unknown; `final` names them. Candidates who withdrew but stayed on the
  ballot keep their votes, which ŠÚ SR counts among the valid ones (flag
  `-1`): the app shows them with a "withdrew" mark, never elected nor in
  the seats line. `results.check` (`ems check`, `ems results deploy`) now
  requires the votes of every counted unit of a mayor's or president's
  contest to be its valid ballots, and a council's within the valid ballots
  and the seats; `ems results final` and `ems make` write nothing that
  fails it, and `ems results fake` keeps to it. A city district with no
  figures of its own no longer shows its known okrsky summed instead.
- **Results in the site, per election.** The results are files of the
  site, `results/<election day>/` (`status.json`, the area and okrsok
  files, as before), read from the site's own origin; the separate Pages
  project `election-map-slovakia-live` (`live.volebnamapa.sk`) is no
  longer read, and the CSP's connect-src is `'self'` alone. The definitive
  2026 packages are pinned inputs, `results-oso2026` and
  `results-osk2026` (with copies in `data/fallback/`; a later election's
  are `results-oso<year>`, `results-osk<year>`), and a new step of
  `ems make`, `results` (after `basemap`), writes the final results from
  them into `data/build/results/<election day>/`, as of the packages'
  data, so every release carries the same results; `build` copies them
  into `dist/` and hashes them into the data version, `dist/_headers`
  revalidates `status.json` on every load, `ems check` verifies them, and
  the size report has them as a group. `ems results poll`, `final` and
  `fake` write the election's results directory by default (`--dir`
  elsewhere); `final` reads the pinned inputs when configured, else
  downloads the packages; `ems results deploy` and `poll --deploy` build
  the site and upload it to the main project as a production deployment.
  `ems results serve`, `live_url`, `live_pages_project` and
  `EMS_LIVE_URL` are gone: `ems serve` serves the results, and a build
  with `EMS_RESULTS_ANYTIME=1` reads them at any time, for testing. The
  old project and its `live` DNS record can be deleted (docs/deploy.md).
- **Base map.** A faint base map under the election colours, for
  orientation: rivers, larger streams, lakes and reservoirs, roads by
  class (minor streets from zoom 13) and railways, from OpenStreetMap
  (Geofabrik's extract of Slovakia of 1 January 2026, pinned; ODbL, see
  NOTICE). A new step, `ems basemap` (in `ems make` after `geo`), writes
  it per okres at the shards' levels of detail and a coarse file for the
  country view (`base/`, 239 files, 17 MB, 6.2 MB gzipped); the map draws
  it above the area fills and below every border and label, at a theme's
  opacity, and the layers menu switches it off. A new input kind `pbf`;
  `ems check` verifies the base map against the shards and its index.
- **Results awaited.** After the polls close and before anything is
  counted, the line under the site's name says that the results are
  awaited and will appear as they come in, instead of nothing.
- **Counted, votes not yet published.** A contest counted without its
  candidates' votes (on election night a municipality's turnout, its
  winners at most) says so in a note above its candidates, so that rows
  without votes do not puzzle.
- **Seats on a partial count.** On a partial count of a municipal or
  regional council, the candidates who would win a seat so far have their
  numbers in the results' green, and a dashed line labelled with the seats
  follows the last of them, its tooltip explaining it.
- **2022 turnout of a council constituency.** Where a municipality elects
  its council in several constituencies, a constituency's 2022 turnout was
  the whole municipality's, the 2022 constituencies having been drawn
  otherwise. Now it is that of the polling districts (okrsky) that make up
  the constituency in 2026, where the municipality's decision says which
  they are and it has the same polling districts as in 2022; the tooltip
  names them.
- **Polling districts (okrsky).** The municipalities of several council
  constituencies have their polling districts transcribed from the
  decisions that set them (`okrsok-rules` jobs): which make up each
  constituency, and their streets. The pipeline draws them within the
  constituencies. The municipalities that elect
  their council in one constituency but vote in several polling districts
  (456) get `okrsok-rules` jobs too, their polling districts drawn within
  the whole municipality (`okrsky/<obec>.toml`).
- **Polling district areas and addresses on the site.** `ems geo` cuts the
  polling districts from the municipalities' map features at every level
  of detail and writes them per okres beside them
  (`geo/okrsky/<okres>/<lod>.json`, listed in `geo/index.json`; a line code
  of its own for a border between two polling districts), replacing the
  pipeline-only GeoJSON of `data/build/okrsky/`; `ems addresses` gives each
  address its polling district where they are drawn (`okrsok`, `okrsky` in
  `addr/<obec>.json`); `ems check` requires the polling districts to tile
  their municipality and the addresses to have one exactly there.
- **Data per election.** The curated data the state sets anew for each
  election, the constituencies and now the polling districts, are kept per
  election, in `data/curated/elections/<election day>/`, so that a later
  election adds its own instead of changing these.
- **Final results per polling district.** `ems results final` (and
  `ems results fake final`) also write each contest's figures per okrsok,
  from the 2026 packages' tables per okrsok, in files of their own beside
  the results' area files (`okrsky/<area>.json`), with an okrsok's 2022
  turnout where the municipality kept the same okrsky (417 of 630).
  Bratislava's and Košice's city-wide results go to their districts'
  okrsky; the few that cannot be matched (9 and 5) are left out.
- **Polling districts in the app.** The polling districts are an overlay
  of their own, drawn and numbered when zoomed in; a click or an address
  found by the search says its polling district. With the final results,
  the units' figures and a polling district's 2022 turnout show in a
  tooltip under the pointer, and the candidate card lists where a
  candidate's votes came from, the polling districts with the most votes
  and the highest share.
- **Results at every map level, and per unit on the ballots.** The results
  on the map follow the zoom as the boundary overlays do, for every mode:
  regional constituencies, then municipalities, from zoom 11 the council
  constituencies of a split municipality (any contest's polling districts
  summed per constituency), from zoom 13 the polling districts drawn, on
  one scale over all of them, each unit labelled with its value and named
  with its figures under the pointer; the legend says by which units,
  replacing its municipalities/polling districts switch. Every counted
  contest, councils too, can colour the map by who got the most votes
  where (for a council its top candidate, not those elected); switching
  between a contest's candidates, turnout and most votes keeps the view
  instead of fitting the map to the contest again. On the
  ballots, a contest's results and turnout can be narrowed to the place's
  municipality, council constituency or polling district, one choice for
  all contests, kept while browsing places. A street or part chosen in
  the search is named with its polling district where all its houses
  share one, else with its polling districts' and constituencies' numbers.
- **Every mayoral candidate as soon as a municipality is counted.** On
  election night ŠÚ SR publishes a municipality's mayoral candidates'
  votes as soon as it is fully counted, not only once every municipality
  is: `ems results poll` now fetches them then (and the council
  candidates' too, once published), so that the contest shows every
  candidate's votes and share, final, instead of the elected mayor alone.
  Files that a poll finds due (a municipality just found fully counted)
  are fetched in the same poll, not at the next change of the count.
- **The count's progress no longer reads 0 % once it has begun.** The
  status line and a contest's count give how far the count has got in
  tenths below 10 % and as "< 0.1 %" below that, since the small
  municipalities, counted first, are a fraction of a per cent of the
  voters: 163 municipalities counted read "municipal 0 %" before.
- **Regional turnout per municipality on election night.** ŠÚ SR
  publishes a municipality's regional turnout once it is counted, but its
  votes only later; the live results now carry that turnout meanwhile, so
  that the regional turnout map shows each municipality counted, while a
  candidate's map shows its constituency as a whole there.
- **Councillors known before their votes.** Where a counted council has
  as many seats filled as candidates (every seat, or more seats than
  candidates), the app marks them all elected, though ŠÚ SR has not
  published their votes yet. A withdrawn candidate still listed leaves a
  seat fewer filled, so then nothing is marked.
- **Definitive results straight from volbysr.sk, in their 2026 form.**
  `ems results final` without arguments downloads both elections' CSV
  zips and keeps them under `data/raw/results/`. It reads the 2026
  tables, which differ from 2022's (comma-separated, columns named in
  full, summed per municipality, constituency and kraj, the two cities'
  own contests in tables of their own), and refuses a package lacking a
  table or column it reads. A council constituency's seats come from the
  candidate lists where the tables give only the whole council's.

## 0.4.0 — 2026-10-24

- **Live 2026 results.** On election night the site shows the results as
  they are counted and, from the next day, the final ones, without a new
  release: they come from a site of their own, `live.volebnamapa.sk` (a
  second Cloudflare Pages project holding only the results), which the
  page reads from the polls' closing, every minute while it is in view,
  for a week (`live_days`), and after that once per page load, so that a
  page left open or an old copy of the site stops polling.
  - While the polls are open (07:00–20:00 Slovak time), a line under the
    site name says the voting is under way and when the polls close, with
    a still bar of how much of the voting day has passed.
  - Then a status line tells, in a line where it fits, how far the count
    has got and the time of the results (Slovak time, 24-hour clock);
    each contest says whether it is counted yet, and while counting how
    much of it and how many valid votes, and its candidates are listed by
    votes, each with a bar of their share. How far a count has got is the
    share of the registered voters whose polling districts are counted,
    each district whole however many voted there, so that districts of
    every size weigh as they should (those still to count estimated from
    the last election); the districts counted are in the tooltip.
  - A council's seats, where only the 2022 number was known, are the 2026
    number once the results give it.
  - The elected get a medal, an eight-pointed star on a ribbon in the
    results' own green (which past figures never use), the one badge
    without a ring, as only winning earns it. It stands right after the
    name, before the parties, as these elections elect persons rather
    than parties. "Elected 2026" is a filter mark like the others, and
    Favourites count the circled elected. A council's substitutes are not
    marked: they are all its other candidates with a vote, in the order of
    their votes.
  - A winner is called before the count ends only when no uncounted vote
    could change it: when fewer rivals than seats could still reach them
    even if every registered voter of the districts not counted yet voted
    (at most the registered voters at the last election plus 10 %). Such a
    call's medal is drawn in outline, and its tooltip says what it rests
    on.
  - The map can colour by one candidate's share (a pin at the end of their
    row, under the contest's own) the areas of their contest, or for a
    mayor or council candidate their one municipality or council
    constituency, in shades of the results' green; or every municipality
    by the turnout of the municipal elections, of Bratislava's and
    Košice's own elections of a city mayor and council (on ballots of
    their own), or of the regional elections (the boundaries
    menu, or one contest's from the pin in its header, pressed again once
    the area is shown), in shades of the colour the area is drawn in (a
    municipality's red, a council constituency's orange, the cities' green,
    a regional contest's violet), so that nothing changes colour. The scale
    spans the values shown (30–50 % where every area lies between them),
    the areas not counted yet left out of it; the labels give the values,
    and a legend the scale. A regional contest is coloured by municipality
    where the night brings each municipality's votes once it is fully
    counted (by regional constituency until then), and by municipality in
    the final results.
  - `ems results` makes the live site: `poll` follows the count on
    volbysr.sk and writes `live/` when it changes, `final` reads the
    definitive tables, `fake` writes dummy results of five stages of the
    night to test with, `serve` and `deploy`. See
    [docs/results.md](docs/results.md).
  - Search engines learn of it too: the pages' title, description and the
    text they read without running the page name the live results.
- **A map pin on every contest of a place's ballots**, as on a candidate's
  card: here and in Favourites it fits the map to the contest's area (the
  municipality, a council or regional constituency, the city, the
  self-governing region) and highlights it, leaving the place selected,
  its ballots and Favourites open as they are, so that the pin's next
  press (the turnout) is at hand.
  Every contest's pin is in the colour its area is drawn in on the map;
  a candidate's votes pin in the results' green.
- **A release reaches every browser at once.** The code is now under
  `/assets/<version>/`, named by a hash of it, and browsers keep it for
  good; the data files are fetched with the hash of the data appended, so
  a release replaces the browser's copies on the next page load instead of
  after a few minutes, and an unchanged part stays cached. The libraries
  and the images (party logos) have folders and hashes of their own, so a
  release that changes only the app's code leaves them, and the data,
  cached.
- **Favourites as a QR code.** A second button by the Favourites title
  shows the link to them, with the filter, as a QR code in a dialog of its
  own, as large as the screen allows and white in the dark theme too, for
  another device's camera to open them there. It follows every change; a
  link too long for a code says so.
- **Past turnout in every contest's header.** At the end of each header a
  short horizontal meter, like the candidates' vote bars, gives the
  turnout of the last election in the contest's area, its share and year
  above it, without making the header taller; the tooltip gives the
  numbers (who voted of all registered) and which election that was (the
  2022 elections, or a municipal by-election since). A council's figures
  are of the whole municipality where it now has several constituencies,
  as the 2022 ones were drawn otherwise; a regional constituency's are
  summed over its municipalities. Once counted, the meter shows the 2026
  turnout in green, the last election's left on it as a grey tick with
  its figures under it, so that the two compare at a glance.
- **Cross candidates out; hide with one press.** Every button on a
  candidate row now has an alternate press, Shift+click or a double click
  or tap. On the ballot number it crosses the candidate out with a red
  cross (the opposite of circling, which it replaces): the list then mutes
  the candidate like those the filter excludes, the filter bar counts the
  crossed out, and the link carries them (`x`). On a party tag or a mark
  it adds the party or mark to the filter with its candidates hidden,
  where a plain press shows only them; each press, repeated, undoes
  itself. With Shift held, the pointer previews the alternate press: a
  faint cross on a number, a faint dashed ring on a party tag or a mark.
  Each party in the filter now has its own mode, so that some parties can
  be shown and others hidden at once; links made before read as they did.
  The tooltips and the help say how.

## 0.3.1 — 2026-10-23

- **Serious controversies apart from allegations and disputes.** A
  controversy is now serious only when it is established: charges brought
  by the police or prosecutors (or detention, an indictment), a court
  decision against the candidate, or another serious matter an authority
  established (a binding conflict-of-interest sanction, an audit finding,
  removal from office). Everything else, such as an opponent's allegation the
  candidate denies, a criminal complaint with no charges, a case that ended
  in the candidate's favour or a political quarrel, is among the
  allegations and disputes, and so is a finding in doubt. Of the 383
  controversies found so far, 53 (on 38 candidates) remain serious and 330
  are allegations and disputes; 190 candidates had only those. The serious
  ones keep the red warning mark and the red edge of the row; allegations
  and disputes get an amber mark of their own, a question mark in a
  circle, a filter of their own and a section of their own on the
  candidate card, each kind with a line on what it holds. Research
  reports the two kinds from now on.

## 0.3.0 — 2026-10-23

- **Circle your candidates, as on the ballot, and share them.** A
  candidate's ballot number now circles the candidate, in pen blue, on the
  ballots and on candidate cards. A contest counts its circled candidates
  and, when more are circled than are elected, flags the number of seats:
  on the ballot itself that would make it invalid (circling more is still
  allowed, to choose among them later). Circled candidates stay listed in a
  closed contest, and the filter never mutes them. A new round button with
  a heart, Favourites, below the others, shows the number circled and opens
  a list of every circled candidate's contest, the circled first and the
  rest a click away. On a wide screen the list opens beside the pane, as
  wide as the screen allows, and the pane keeps the ballots or the card of a
  candidate picked in the list; a place found by the search closes it, as
  it would hide the place. On a narrower screen the list is what the pane
  shows. The circles, the filter and whether the list is open are now kept
  in the page's address, so a link shares them, and a link button by the
  list's title copies a link to them, with the list open, without the place
  shown on the map. Back and Forward still go from place to place and keep
  the circles and the filter.
- **Regional contests on the map.** The pin of a regional president's or
  regional council's contest, on a candidate card or in Favourites, shows
  the self-governing region or its regional constituency on the map, as
  those of municipal contests show theirs.
- **About names the site's version.** The About dialog's line on the
  source code now starts with the site's version, its number linked to that
  version's release on GitHub with its notes.
- **Releases do not depend on the past results' server.** Two days before
  the elections, volby.statistics.sk answered 404 for every past results
  file (2022 and the by-elections since), which would have stopped the
  release at `ems fetch`. Those files never change and are pinned by their
  sha256, so copies of them are now committed in `data/fallback/`: when the
  server of a pinned input fails, `ems fetch` takes the copy on disk or the
  committed one, if it has the pinned digest, and warns.
- **Floating controls are opaque.** The search card, the round buttons, the
  zoom buttons and their menus no longer blur the map behind them: with any
  backdrop filter on the page, however light, Firefox dropped about twice
  as many frames while the map was panned. They now have the solid
  background the pane already had. Dropping the blur only while the map
  moves was measured too: it saved less, varied more, and the controls
  would change look at the start and end of every pan.
- **The map draws about three times faster when zoomed in.** The dashed
  borders (of the countries around, and the approximate council
  constituency borders) were dashed by the canvas along their whole
  length, which zoomed in runs on for hundreds of views beyond the one
  drawn: at street level that was two thirds of each drawing. They are now
  dashed only where the drawing shows them, with the dashes where they
  were. A drawing at street level on a 2× screen takes about 29 ms instead
  of 94 ms in Firefox and 26 ms instead of 74 ms in Chrome, so the map
  keeps up with a pan, and a fast fling no longer shows blank edges.
- **Michalovce researched again in the Slovak media.** The 101 candidates
  for mayor and city council were searched again, thoroughly, in the
  Slovak media (Korzár included): 64 findings on 29 of them, 10 of them
  affairs, where the first run had 9 findings on 5. Their findings from
  official sites are unchanged.
- **Košice region researched again in the Slovak media.** The 6 candidates
  for regional president now have 26 findings (10 affairs), up from 18,
  with court cases brought up to date. The 29 candidates for the regional
  council in the Michalovce constituency not covered by the Michalovce
  rerun have 23 findings on 7 of them (13 affairs), up from 1. The new
  findings of both reruns are translated into every language.
- **Declined names pass the translation check.** The check that a
  translation is in its language's script let a Latin-script word through
  only in the source's exact form, so a name declined by the translation
  (Czech "Maroše Eľka" for "Maroš Eľko") was rejected and translators wrote
  names in Cyrillic or left them out. A capitalised word that is a source
  name with another ending now passes; the Ukrainian and Rusyn prompts ask
  for names in Latin script in their basic form, and the affected Czech,
  Ukrainian and Rusyn translations are redone that way.
- **Pages turned away come from the Internet Archive again.** When sme.sk
  turned a cited page away, the archive's snapshot was looked up with its
  availability API, which answers 429 under load; that was taken for "no
  snapshot", so Korzár articles the archive has were rejected. The lookup
  now asks the archive's CDX index, and a failed lookup says so ("try again
  later") instead of claiming there is no snapshot.

## 0.2.0 — 2026-10-21

- **Releases no longer stop on a regional announcement.** The regional
  constituency announcements are records of the sources of the curated
  regional constituencies, read by no step. They are now `optional` in
  `config/inputs.toml`: if one cannot be downloaded (two regional servers
  timed out or refused GitHub's runners, failing the 0.1.0 release),
  `ems fetch` warns and the release goes on.
- **Sitemap.** `sitemap.xml` lists the root page and every language's page
  for search engines.
- **Search engines.** The root page, which picks the language, carries a
  description and a heading like the language pages, and the Seznam
  Webmaster verification tag.
- **What the site offers, in search results.** The pages' description for
  search engines now names the main features (ballots by address, the
  candidates, who holds office now, sourced notes on them), and a short
  paragraph on what the site does is on the root page and, for search
  engines that do not run scripts, in every language's page.
- **Search results over the filter.** The candidate filter and the pane's
  close button no longer cover the search results.
- **Search results beside the pane.** On a screen 960 px wide or more, the
  search results open to the right of the open pane rather than over its
  candidates.
- **Steadier labels.** An area's label moved into view (its own spot panned
  away or under the pane) stays where it is while the map pans, until the
  edge of the map or a pane reaches it, instead of following the middle of
  the area in view; opening or closing the pane moves the labels it covers.
- **No names cut off.** A name of a district, municipality or obvod that
  the pane or the edge of the map would cut off moves to the part of its
  area in view, or is left out where it has no room there; a region's name
  slides out from under the pane.
- **Labels follow the map as it glides.** The map is drawn again as it
  pans, so the labels at its edges keep in view while it is dragged and
  while it glides on after a drag, rather than jumping once it stops.
- **Researched, nothing found** is marked by a magnifier outlined in a
  muted primary colour, apart from the faint grey, dashed mark of a
  candidate not researched yet.
- **More candidates researched.** 1,440 more mayoral candidates, from the
  largest towns down, were researched in the Slovak sources (181 of them
  with findings, 273 findings, 77 controversies), and so was every
  remaining regional council candidate, 1,359 more (163 with findings,
  222 findings, 72 controversies), and every city council candidate of
  Martin, Poprad, Prievidza, Zvolen, Považská Bystrica, Nové Zámky,
  Komárno, Spišská Nová Ves and Levice, 541 more (38 with findings,
  46 findings, 7 controversies), and 500 more picked as the likeliest to
  have coverage: sitting councillors of mid-size towns, professors and
  docents, mayors of larger villages, deputy mayors and officials (42 with
  findings, 54 findings, 8 controversies): 7,598 candidates in all.
- **Research findings in every language.** The claims and quotes of all
  7,598 researched candidates are machine-translated into Czech, Hungarian,
  Polish, Ukrainian, German, Rusyn and Romani, and the quotes into English
  too; only four quotes that are bare lists of names or contacts stay in
  the original in some languages.
- **Mixed-script words caught.** The translation check rejects a word with
  letters of another script inside it, such as a Latin "á" in a Cyrillic
  word; it used to look at a word's first letter only.
- **Research of chosen candidates.** `ems job make research --only` takes
  `person:<id>`, so a list of candidates worked out elsewhere can be
  researched in its order.
- **Screenshot script.** `scripts/screenshot.py` takes the README's
  screenshot from the built site with any Chromium-family browser, using
  only the standard library, so it can be retaken for each release.

## 0.1.0 — 2026-10-20

The first release: a map of every constituency of the Slovak municipal and
regional elections of 24 October 2026, with the candidates standing in each.

What it does:

- **Every constituency on one map.** Municipalities and city districts from
  the ZBGIS boundaries, the regional constituencies, the city council
  constituencies of Bratislava and Košice and the municipal council
  constituencies, each an overlay of its own that appears as one zooms in.
  Council constituencies come from the municipalities' own resolutions,
  transcribed into rules by street and house number and checked against
  every address; the few municipalities that publish only names get an
  estimate, labelled as one. The map is drawn by the site itself, in a
  worker, without map tiles; it pans and zooms smoothly and follows the
  device's light or dark theme.
- **Every ballot of a place.** Click the map or search for an address, a
  municipality or a candidate: the address register gives the exact
  constituency of a house. The ballots list the most local contest first,
  with the seats and the number of candidates, and can be filtered by party,
  current office or research findings.
- **Candidate cards.** The official data of each candidacy; each of the
  candidate's contests, which opens to the other candidates (the filter
  applies to them, never to the candidate) and has a pin that shows the
  municipality, city district, city or constituency on the map; the offices
  a candidate holds now and how they won them, from the final results of
  2022 and of every by-election since; and AI research from an allowlist of
  media and official sites, each finding backed by a verbatim quote, a link
  to the source and a kept copy of it, controversies first and flagged in
  every list.
- **Nine languages.** Slovak and English written by hand; Czech, Hungarian,
  Polish, Ukrainian, German, Rusyn and Romani machine-translated and
  labelled as such.
- **About.** A short page with the project's purpose, its source code on
  GitHub and its license, and sections on how it works, the data sources and
  their licenses, the sources of the candidate research and the
  disclaimers.
- **Static and private.** The `ems` pipeline downloads the official inputs,
  builds plain files and checks them; the browser loads nothing from other
  servers, which the Content-Security-Policy enforces.
- **Releases.** A push runs the checks; a version tag builds the site,
  deploys it to Cloudflare Pages at https://volebnamapa.sk and creates a
  GitHub release with the site attached.
