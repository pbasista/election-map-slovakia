# The frontend

`web/` holds the frontend:
ES modules with no build step, Preact + htm for the components
and Leaflet for the map view.
`ems build` copies it into `dist/app/`, the app's part of the site,
under versioned paths
([pipeline.md](pipeline.md#build)).
The whole page is the map;
a pane beside it (a bottom sheet on phones) shows the ballots of a place.

## Files

| In `web/` | In `dist/` | What |
|---|---|---|
| `app.css`, `js/` | `/assets/<v>/` | the styles and the ES modules |
| `vendor/` | `/assets/vendor/<vv>/` | Leaflet 1.9.4, Preact + htm, the QR code generator |
| `img/` | `/assets/img/<iv>/` | party logos |
| `cache.css` | `/assets/` of the sources part | the stylesheet of the cached copies |
| `index.html` | `/<lang>/<slug>/`, `/<lang>/` | the app shell, a template: one page per language and election, the home election's also at `/<lang>/` |
| `picker.html` | `/` | the root page that picks the language, a template |
| `i18n/<lang>.json` | `/i18n/` | the hand-written UI strings, Slovak and English |
| `_headers` | `/_headers` | the base of the app's response headers |

Each version (`<v>`, `<vv>`, `<iv>`) is a hash of its tree.

- **Vendored libraries.**
  Leaflet is its `dist/leaflet.js` less the source-map comment,
  since the map is not shipped.
  The modules import the libraries as `'../vendor/…'`,
  so `web/` runs as it is;
  the build rewrites that prefix to `/assets/vendor/<vv>/`
  in the modules directly in `js/`, where it means `web/vendor/`.
- **UI strings.**
  The build adds the other languages' UI strings
  ([agent-jobs.md](agent-jobs.md#translation)).
  The occupations' translations are in each election's data bundle,
  `i18n/<lang>.json` there (none for Slovak, in which they are written),
  fetched with `fetchJSON` like its other files (`js/data.js` `occupations`).
  The card and the tooltip of a translated occupation give the Slovak original;
  party names stay as the official lists write them.
- **Search engines.**
  `app.description.<kind>` is the search engines' description of a page
  of an election of that kind,
  `app.title.<kind>` its title.
  `app.features.<kind>`, what the site offers in a paragraph,
  is in an app shell's `<noscript>`
  for search engines that do not run the page's scripts.
  The home election's page `/<lang>/` is the site's front page:
  its description and `<noscript>` start with the site's own,
  `site.description` and `site.features`,
  which name every kind of election the site shows
  and the year of the oldest (`{since}`);
  the root page has the same texts,
  the paragraphs in each fallback language
  (build.py `_texts`).
  The `site.*` strings list the kinds by name,
  so a new kind of election needs them revised.

## Elections

Each election (`config/elections.toml`) has its own pages,
`/<lang>/<slug>/` (`/sk/2026/`),
and `/<lang>/` shows the home election,
whose `/<lang>/<slug>/` page names it as canonical:
the newest by day, an upcoming one included,
so that the site opens on the most recent or the upcoming election,
but never a by-election,
which is held in a few places only and concerns few visitors
(`Config.home`).
An election's kind (`kind` there: `municipal-regional`, `by-election`,
`presidential`, `referendum`, `parliament`, `european`)
decides what the page shows;
`js/kinds.js` mirrors `contests.py`
(contest ids taken apart, `electionKind`, `isNational`, `isByElection`,
`areaName`) for every module.
A page shows one election and loads only its files,
those of the election's two bundles, each a part of the site of its own:
its map (`geo/`, `addr/`), which depends on that election alone,
and its data (`data/`, `i18n/`),
and those of the base map of its OpenStreetMap extract (`base/`),
a part of its own that every election on the extract shares
([pipeline.md](pipeline.md#build)).
The shell's config (the `km-config` meta) gives

- `election`, its day, and `elections`, every election as `{day, slug, kind}`,
  newest first (`js/i18n.js` `election`, `elections`);
- `map`, `data` and `base`, the addresses of its bundles and its base map
  (`/map/2026`, `/data/2026` and `/base/osm-slovakia-2026` under
  `ems serve`, deployed the addresses of their deployments, each on an
  origin of its own);
  `js/files.js` `dataUrl` and `fetchJSON` put the map's before every path
  below `geo/` and `addr/`, the base map's in place of `/base` before
  every path below `base/` (`/base/index.json` is
  `<base>/index.json`), and the data's before any other path
  of the election's files,
  and the map's renderer gets them all with its options
  (`js/map.js`, `js/draw.js`);
- `mapVersion`, `dataVersion` and `baseVersion`, the versions of the
  bundles and the base map, which their files are fetched with (`?v=`),
  and `stringsVersion`, the hash of the UI strings,
  the same on every election's page so that switching keeps them
  (`js/files.js` `dataUrl`, `sharedUrl`);
  the elections on one extract have the same `base` and `baseVersion`,
  so switching between them keeps the base map's files too;
- `sources`, the address of the cached copies of the pages research cites
  (empty under `ems serve`: the site's own origin);
  a card links a copy as `<sources>/cache/<sha256>.html`
  (`js/i18n.js` `sourcesBase`);
- `logos`, the directory of the party logos,
  which data/index.json names by file (`js/i18n.js` `logoUrl`);
- `occupations`, for each language but Slovak,
  how many of the election's occupations its data bundle has not translated:
  the app says the translation is incomplete
  where that is more than none or UI strings are pending
  (`js/i18n.js` `translationPending`);
- `previous`, the day of the regular elections before,
  of which the office holders and the contests' past turnouts
  in `candidates.json` are (null if unknown);
  the results' `past` names its own day, each contest's
  (see [The election before](#the-election-before));
- `results`, the address of the election's final results
  (`/results/<day>` under `ems serve`), named even before there are any;
  `live`, that of its live results (`/live/<day>`),
  only for an election with `live` in `config/elections.toml`, else null;
  `polls`, `liveWindow`: the election's;
- `rounds`, of a presidential election only,
  `[[day, polls open, polls close]]` of each round
  (round 2 once configured), which label the rounds' contests
  (`js/i18n.js` `rounds`);
- `credits`, on the page of an election drawn on a later election's
  boundaries (not the newest of its `zbgis` inputs),
  what the map's credits name (else null):
  the later boundaries it is drawn on
  and how many municipalities then differed,
  and the dates of its base map and addresses
  (`inputs.toml` `as_of`; build.py `_credits`).
  The credits there read, say,
  "Boundaries: ZBGIS 2026 … (2022 boundaries differ in 16 municipalities)
  · Base map: … as of 1 January 2022 · … Addresses: MV SR, 09/2022"
  (`js/map.js` `attribution`).

**Switcher.**
The search card's title is one row, 40 px high (`js/search.js`),
its parts centred on it, the card 56 px high:
at its left the site's logo, a map pin;
beside it two lines, the page's heading:
the site's name (`app.name`, 15 px, semibold)
over the tagline, the page's election's name and its date written out
(`electionParts`, 12 px, a step under the site's name),
as the election is named everywhere else;
at its right the round search button, as large as the pin.
The names are the short, widely accepted ones in every language,
no abbreviations ("Parlamentné voľby", "Prezidentské voľby",
"Voľby do Európskeho parlamentu"; "Parliamentary election",
"Presidential election"), and so are the list's headings
(`elections.kind.<kind>`).
Name and date are joined by `elections.item` ("{name} {date}",
the order and any words as the language puts them), with no comma:
the title renders the template's parts as elements of their own,
in three steps under the site's name in the text's colour:
the election's name in the tagline's dimmer colour and a little bolder
(500; 8.8:1 on the card light, 9.4:1 dark), the date fainter still
(5.8:1, 6.9:1), a fifth of an em apart (`.tagline-name`, `.tagline-date`);
tooltips, screen readers and sentences use the same words as one string
(`electionName`).
The tagline keeps to one line:
beside the map (from 641 px) the card is as wide as it needs,
from the pane's width up to the buttons on the right,
but as wide as the pane while Favourites stand beside it;
where the card cannot grow (a phone, Favourites beside),
the tagline's type shrinks to fit
(`fitTagline`, from 12 px down to 10 px, run before paint and on a resize
only), and what does not fit even then takes two lines of 10 px,
balanced, rather than lose its end, the row growing with it (the card
61 px).
On a phone 390 px wide every name fits one line in every language
(10–12 px); on one 360 px wide all but the longest do,
the municipal and regional elections in Hungarian, Polish, Ukrainian and
Rusyn and the European Parliament election in Polish and Ukrainian
taking two lines.
Where the site has several elections, the pin is the button
that opens the list (`elections.open` its label,
the full name in its tooltip), round and tinted as the search button,
with the page's election's kind's icon in a badge at its corner,
in the kind's colour.
Its cover takes the card from its left edge to the search button,
the name included; the search button the rest:
two targets, each the card's full height.
The search box and the list take the title's turn in the same cell of the
card's grid, the title kept there unseen,
so that the card is as high and as wide with the search box
as with the title, the box centred in it,
and the pane under the card stays put.
It turns the card into the list of elections, like the search does,
under a header with its title (`elections.label`),
the two views' buttons and the close button;
no higher than the screen, the list scrolls under them.
The views (`elections.view.<view>`, the one shown pressed):

- The timeline, the default: every election, newest first
  (as `elections` lists them), as a point on a line down the left,
  its kind's icon in a ring in the kind's colour;
  beside it its date, written out as the title writes it,
  and under the date its name (`elections.name.<kind>`,
  the half of a regular election before 2022 named as such).
- The groups by kind of election (`kind` in `config/elections.toml`),
  each under its heading (`elections.kind.<kind>`, with the kind's icon),
  the kind of the newest election first,
  so that another kind of election reads as another group;
  in each, its elections, newest first, as many to a line as fit:
  its date, a regular election of one half before 2022
  naming the half under it.
  The headings are set like the site's name in the title.
  Each is a disclosure button that folds or unfolds its group;
  the by-elections, many and of a few places each, start folded,
  the others unfolded,
  and the visitor's choice is kept across visits and elections
  in `localStorage` (`election-map-slovakia.elections`, every kind's state;
  with storage disabled, for the visit).
  A folded group still lists the page's own election,
  so that the list always shows where the visitor is.

The view chosen is kept likewise
(`election-map-slovakia.elections-view`, `timeline` or `kinds`).
In either view each election is a link to its page `/<lang>/<slug>/`,
the current one tinted, checked and focused
(in the timeline its ring filled).
The arrow keys move through the headings and the elections shown,
Esc closes the list and gives the focus back to the button that opened it.
A screen reader hears the whole name (`electionName`).
A link keeps the map view and the place (`m`, `o`, `ll`, `a`;
`carriedHash`) and drops the rest of the hash,
which names contests and candidates of one election,
but for the open candidate (`c`):
where the person is linked to a candidate of that election,
the link opens theirs, the candidacy for the same office if there is one
(data.js `candidacyLinks`).
With one election there is no such button: the pin is just the logo,
and the whole title is the search button's.

**Kinds' marks.**
Each kind of election has an icon (`js/icons.js` `KIND_ICON`:
a town, a ballot with a plus, a person with a sash, a ballot asking,
a building under a dome, a ring of stars)
and a colour of its own, muted and readable on the card
(`web/app.css` `--kind-<kind>`, light and dark);
`js/kinds.js` `kindIcon(kind)` and `kindStyle(kind)`
(the latter sets `--kind` on an element, which `.kind-mark` reads)
take a kind or a label, `municipal` and `regional` being
of the municipal and regional kind.
The switcher's button (the badge on the title's pin), the timeline's points
and the groups' headings use them.

**Strings per kind.**
The title's tagline is `elections.name.<kind>` with the date
(`elections.item`),
the switcher's headings `elections.kind.<kind>`,
its timeline's names `elections.name.<kind>`,
About's list of what the page offers (`about.feature.<item>`,
the items chosen by kind, below),
and the shell's title, description and `<noscript>` paragraph
`app.title.<kind>`, `app.description.<kind>`, `app.features.<kind>`
(on the front page after the site's own, above).
The kinds' own strings come in families
(`president.*`, `referendum.*`, `party.*`, `contest.*`, `byelection.*`,
`scope.country`, `scope.kraj`, `scope.okres`, `mapmode.held_*`),
written in `web/i18n/sk.json` and `en.json`,
the other languages by the translation job.

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
  the constituency overlays the election has
  (regional councils, Bratislava and Košice, municipal councils,
  polling districts where drawn; map.js `overlaysHere`;
  none, no button: a country-wide election has none of the first three,
  a by-election seldom any, the regional or municipal elections
  held apart before 2022 only their own: 2017 the regional councils,
  2018 Bratislava and Košice and the municipal councils;
  data.js `electsAnywhere`),
  with when each appears and the legend of those on
  folded under "What the lines mean";
  the ballots, behind the ballot box (icons.js `TurnoutIcon`):
  of a party-list election or a referendum (`kinds.js` `overviewKind`),
  the [Overview](#overview) shown or not,
  so that it opens without a place picked first;
  once counting has started, the election's turnouts on the map
  (mapmode.js `turnoutChoices`) under it;
  each a checkbox that a second press clears,
  at most one turnout at a time, as the map shows one mode,
  the overview on its own;
  the button dotted while either is in effect
  (no button where the election has neither);
  and the base map:
  roads, railways and water, and buildings.
  The overlays and the base map's layers are all on when the page opens.
- **Phones.**
  With the sheet open, the buttons above the zoom
  go under one ⋮ button that puts them out in their column.
- **Status line.**
  While the polls are open (elections.toml `polls_open`, `polls_close`),
  a line under the site name says the voting is under way,
  with a still bar of how much of the voting day has passed.
  After they close, while nothing is counted yet
  (status phase `none`, or no results to read yet)
  and the results are still polled,
  it says that the results are awaited and will appear as they come in.
  Once counting starts, the count's status takes its place
  (`js/live.js` `LiveStatus`):
  how far each of the election's sources has got
  (the regional and municipal elections,
  a presidential election's rounds, the country)
  by the registered voters whose polling districts are counted.
  The voting bar uses the election's `polls`
  (of a presidential election, round 1's hours).
- **Pane.**
  Clicking a place or a search result opens a pane with the ballots there
  (a bottom sheet on phones).
  With no place chosen, it opens by itself
  on the country's ballots of a country-wide election
  and on where a by-election is held
  (see [Country-wide elections](#country-wide-elections),
  [By-elections](#by-elections)), until it is closed.
  It closes with its button, Esc or, on phones, a swipe down.
  With Favourites or the overview open beside it (or in it), Esc closes
  those first, wherever the focus is, as they were opened from the pane.
- **Theme.**
  The theme follows the device unless chosen in the theme menu
  (kept in localStorage);
  `js/theme.js` applies it before the first paint.

## Ballots

### Contests and notices

A place's ballots and a candidate's candidacies list contests
in the same order, the most local first
(data.js `localFirst`):
the municipality's or city district's,
then Bratislava's or Košice's, then the self-governing region's;
of one area the council before the mayor or president;
the country's last (`countryOrder`: a presidential election's
latest round first, a referendum's questions in order,
a party's list after its party contest).
A by-election's place has only the contests held there
(data/index.json `held`);
a regular election of one half (before 2022) only that half's
(kinds.js `holds`).
The municipal and the regional contests stand under headings of their own,
each only where it has contests:
a half not voted on there is neither headed nor said to be missing
(no "no council election" in a regional election).
A country-wide election's ballots are the country's, everyone's.

A note above the council contests
(that all its constituencies are listed,
that they are drawn with another vote's borders standing in
(the nearest in time with the same obvody and seats, earlier or later;
named in `{source}` by its kind and year, `stand_in.source.<label>`
from i18n.js `standInSource`) without proof that they match, so only indicative,
`council.adopted`, which comes first,
that their boundaries are approximate or our estimate,
drawn with another election's rules, `council.reused`,
from a document that states no date, `council.dated`,
or partly from a later source where the election's document
does not place every address, `council.supplemented`;
every one that applies is said, the first summarising)
is one line of summary, cut short where too long;
its whole text is the tooltip and unfolds under it on a press
(pane.js `Notice` *summary*).
Once the polls have closed it speaks of the election as past:
where the obvody are not known it says they are not known,
and where no document setting them was found (data/index.json
`not_found`), that it was not found (`council.not_found`),
rather than "not known yet".

Notes of the same kind under the introduction
say what the map draws of the municipality that is not its own
(data.js `ballots` `origin`, from data/index.json):
its polling districts drawn from another election's
or a referendum's documents (`notice.okrsky_reused`,
for a country-wide election, which searches no documents of its own,
`notice.okrsky_copied`; `notice.okrsky_referendum`),
or with another vote's borders standing in without proof that they match,
so only indicative (`notice.okrsky_adopted`, the vote named the same way;
each okrsok standing in though its voters on the roll differ by more than
a quarter named with both counts, `notice.okrsky_outlier`,
from `okrsky_outliers`),
or from a document that states no date (`notice.okrsky_dated`),
each such document with what dates it approximately:
an Internet Archive capture or a posting on that day,
so it is no newer, though perhaps older than the election
(`notice.dated_archived`, `notice.dated_posted`),
or its naming the election (`notice.dated_named`),
polling districts partly from a later source
where the election's document does not place every address
(`notice.okrsky_supplemented`),
each such note, as the council's `council.supplemented`, followed by
the source: a later election's documents, a referendum's,
or another later document of the municipality, of that year,
so the election's borders may have differed there
(`notice.supplemented_election`, `_referendum`, `_document`),
polling districts not drawn though it voted in several, so its results by
polling district cannot be placed on the map (`notice.okrsky_unknown`),
and a boundary drawn as of a later election
that then ran slightly differently, naming the neighbour
the land moved between or the state border (`notice.boundary`,
`boundaries.toml` of the election).
The map's tooltips add the same in a short line
(`mapmode.js` `originLines`).

The documents that set a council's constituencies
follow its contests on one line:
one document's title cut short, or several numbered,
each title in its tooltip (`Sources` in `js/ballots.js`).

### Country-wide elections

A presidential election, a referendum
and the elections to the NR SR and the European Parliament
have the same ballots everywhere (`isNational`;
data/country.json, a party's list in data/list/<p>.json).

- **The pane opens by itself.**
  With no place chosen it shows the country's ballots under "Slovakia"
  (`scope.country`, `ballots.country`),
  so the candidates are there at once;
  closed, it stays closed until a map click or a search
  opens it for that place.
  On a place the header names it,
  the same ballots follow (`ballots.intro_country`),
  their results scoped by the [unit choice](#results-on-the-ballots).
- **Presidential.**
  One contest per round, named with its day
  ("President · round 1 (23 Mar 2024)", km-config `rounds`),
  round 2 first once it exists.
  The candidates' rows give their residence in place of a party.
  A line under the header says what decides the round
  (`president.rule_1`, `rule_2`):
  round 1 is won with more than half of the votes
  of all registered voters,
  else the two best go to round 2, which the one with more votes wins.
  Counted, the rows mark the elected,
  those through to round 2 (an arrow into a 2, `AdvancedIcon`,
  the words in its tooltip and label, `president.advanced`)
  and those who withdrew.
- **Referendum.**
  One contest per question, "Question No. n",
  its wording quoted,
  cut to five lines where longer (`Question`, measured on mount
  and when its width changes) with a button that shows it all
  and cuts it again, its choice kept per question for the visit,
  so that the answers' figures stay in view from place to place;
  screen readers have the whole wording either way;
  and two answer rows, "Yes" and "No",
  with votes, shares and bars once counted;
  answers are not circled.
  The turnout meter marks the quorum (half the registered voters)
  with a dashed line across the track,
  the previous referendum's turnout staying the solid tick
  of other elections, both edged in the background's colour;
  its tooltip and label name both (`referendum.quorum`,
  `referendum.past_tick`), and so do the rules (`referendum.rules_bar`);
  once final, a line says whether the referendum is valid on the question
  and which answer won (`referendum.*`).
- **Parliament and European Parliament.**
  One contest of the parties,
  its facts the seats and how many parties stand,
  then "Rules", a button that unfolds them under the line
  (`contestRules`, folded at first): the threshold
  (a party's, then the coalitions' by their size,
  `threshold` and `coalitions` of the contest)
  and how many preference votes a voter may give.
  A referendum question unfolds when the referendum is valid
  and an answer wins, a presidential round what decides it,
  so that every contest header stays one short line of facts.
  Each party is a row: its ballot number, logo, name, short form
  (which a logo need not spell out;
  its tooltip says it is the short name and gives the full one)
  and the size of its list,
  the list's own facts in the tooltip of that line and of the name
  (`listFacts`: its candidates, how many the filter leaves shown,
  the preference votes a voter may give,
  the count of the party's and the preference votes
  in the unit the row shows, none where the list has no figures of it,
  how many are circled on it),
  and where any are circled, how many,
  warned where more than its preference votes;
  counted, its votes, share and the seats it won
  (a green badge, a person and their number, `SeatsWon`);
  once the result is final, a party without seats,
  its share of the whole country's valid votes below its own threshold
  (a coalition's where it is one), is greyed, less than the filter mutes,
  with the seats' person struck through after its name
  (`NoSeats`, `noSeatsReason`, icons.js `NoSeatsIcon`)
  whose tooltip and label say so with the share and the threshold;
  the national result decides, whatever unit the row shows,
  and nothing is marked while the count goes on.
  After the name, the research marks of a candidate row
  (serious controversies, allegations and disputes, findings;
  `ListResearch`, `party.research_*`) give the totals
  over the list's researched candidates,
  which the build precomputes (the party contest's `research`,
  data.js `listResearch`); plain marks, not filter buttons.
  No line marks the threshold among the parties:
  a coalition over 5 % may still win nothing,
  and a unit's shares would put such a line in several places.
  A party's buttons and tooltips name it a party
  (`party.*`, `mapmode.party_show`), a referendum's answer an answer.
  A press on a party's row opens its list under it
  (`PartyList`, loaded when opened, or with the row's facts):
  straight to its persons as candidate rows
  (number = position, residence in place of a party),
  the first 20 and those circled until "show all",
  and a button that opens it in the overview ([Overview](#overview));
  counted, their preference votes and share of the party's votes
  in the unit the party's row shows
  ([unit choice](#results-on-the-ballots)),
  elected or substitute,
  an icon on one elected thanks to the preference votes
  from a place below the party's seats
  (an arrow up beside a list, `PreferredIcon`)
  and on a substitute (a person beside the arrows of a swap,
  `SubstituteIcon`, in a grey dashed capsule),
  each explained in full in its tooltip and label
  (`party.preferred_title`, `party.substitute_title`)
  and a filter mark like the research's (`preferred`, `substitute`;
  [Circling and crossing out](#circling-and-crossing-out)).
  Counted, the persons are in the order the preference rule gives
  (`byPreference`, `preferenceRank`; [the rule](results.md#country-wide-contests)):
  those whose preference votes reach the quota of the party's votes there
  first, by their votes, then the others in list order;
  of the whole list that is the official order, the elected first,
  and of a unit the rule on the unit's votes, so the order follows the level.
  Each order is made once per record of the results, not per render.
  Where the list has no figures of that unit,
  a coarser unit's never stand in for them:
  its persons show no votes, under a note that they are published
  only for larger areas (`party.list_unpublished`).
  Every package the site has gives them per okrsok
  ([docs/results.md](results.md#national-tables-final)),
  so the note shows only for a unit their tables leave out.
  The ballot number circles a party;
  a second party, or more persons on a list than `preferences`,
  gets the warning of circling more than are elected.
  A list person's card names the party (its logo) and the place on the list.
- Research is done on the regular elections' candidates only:
  a country-wide candidate is shown the research of a linked person
  as on an earlier election's card ([Candidate card](#candidate-card)).

### By-elections

A by-election elects in some places only
(data/index.json `held`: an obec, Bratislava, Košice or a kraj
→ the contests there).
With no place chosen the pane lists them, "Where the vote is held"
(`HeldPlaces`, data.js `heldPlaces`):
each municipality a button that selects it, with what it elects,
obce by name, after them the kraje,
which are named with their contests only
(they concern every municipality in them).
The map tints the places in the accent colour
([Results on the map](#results-on-the-map)).
A place with nothing elected says so and offers the list;
one with something elected shows those contests,
as the regular elections' are shown.
A contest called but held nowhere, no candidate having registered
(data/index.json `uncontested`), is no place where the vote is held,
neither in the list nor tinted,
but its place's ballots show it:
"Called, but not held: no candidate registered.",
with what says so.

### Uncontested contests

A contest called but held nowhere, no candidate having registered
(`uncontested` in `candidates.json`; a regular election's mayor or
council of a municipality where nobody stood, a council constituency
the decision sets but nobody stood in, as Ilava's 6 in 2018),
is on its place's ballots with "No candidate is registered."
(a by-election's: called but not held)
and a line naming what says so, linked
(ŠÚ SR's territorial division, the municipality's or the Speaker's
decision).
On the municipal turnout map its constituency (from their zoom),
or a municipality where nothing was held,
is drawn as a place without a vote,
unlabelled, its pointer saying no candidate registered,
so no vote was held there.

### Contest header

A contest's header shows whether it is open:
tinted when open;
muted, with a grey bar at its side for the candidates it hides, when closed.
Its tooltip says what a press does.
The contest's name, the button that opens and closes it,
takes a line of its own across the header,
so that long names do not break over lines unevenly;
a press anywhere else in the header but its other buttons does the same.

Under the name, the seats, the candidates and the count of the votes,
and beside them, in one column down the list,
a short horizontal meter (`Turnout` in `js/ballots.js`)
gives the turnout of the last election in the contest's area,
the share and the year above it; the tooltip gives the numbers.
Of a regular election's contests
the last election is 2022, or a municipal by-election since
(km-config `previous`, the contests' `past`);
where the candidates give none (an election without office holders,
such as 2022), the turnout then of the okrsok file of the place
(live.js `placePast`), of the contest's own election before:
2018 for 2022's municipal contests, 2017 for its regional ones;
a contest without such figures shows its own turnout alone, once counted.
The last election's figures are

- a council's, where it now has several constituencies:
  of the polling districts that make up the constituency,
  their figures then found as for the map
  (see [The election before](#the-election-before)),
  else (where one of them is not known) of the whole municipality,
  the 2022 constituencies being drawn otherwise;
- a regional constituency's: summed over its municipalities.

Where those figures are not exactly of the constituency
(the polling districts matched by number and voters, or estimated),
the share reads "≈41 %"
and the tooltip names how they were found and explains it.
Once the contest is counted,
the meter shows the 2026 turnout in the results' green,
the last election's as a grey tick on the track with its figures under it,
and is the button that puts the turnout on the map
(see [Results on the map from the ballots](#results-on-the-map-from-the-ballots)).

With the results narrowed to a unit of the place (see
[Results on the ballots](#results-on-the-ballots)), the last election's
turnout is the unit's own, from the okrsok file of the place
(live.js `placeResults`, `placePast`):

- an okrsok's, as the map finds it;
- an obec's, the whole municipality's then (the same area), else its
  polling districts' then summed;
- a council constituency's, its polling districts' then summed;
- an okres's or a kraj's (of a country-wide contest), its municipalities'
  then summed, only where every one of them is known;
- the whole contest's, where the contest's data give none
  (a country-wide contest): the same contest's then, else (a council
  constituency) its polling districts' then summed.

These sums are made with the results
(the okrsok file's `past` `units`,
[results.md](results.md#okrskyareajson)); the app only reads them.
A sum is as certain as its least certain part ("≈" where any is
estimated), and none is shown where a part is not known.
The tooltip names the unit and the election by the year of its figures
(a referendum's being the vote before of whatever kind).

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
  ("Whole contest | <municipality> | Constituency No. k | Polling district No. n";
  of a country-wide contest
  "Slovakia | <kraj> | Okres <okres> | <municipality> | Polling district No. n";
  of a regional president
  "Whole contest | Regional constituency No. k | <municipality> | …";
  only those that differ from the whole and from each other)
  switches the candidates' votes, shares and bars, the valid votes
  of the header's count line (and of a party's list, the party's votes
  and its persons' preference votes, the results' `preferences`,
  in its row's tooltip) and the turnout meter to that unit.
  The units are, each as the results have it summed
  (the app never adds up figures itself):
  - the kraj and okres of a country-wide contest,
    its municipalities' `areas` summed
    (the record's `units`);
  - the regional council constituency of a regional president
    (the record's `units`, `zsk`: its municipalities summed,
    or at night as counted whole);
  - the municipality or city district
    of a regional, Bratislava's or Košice's city
    or a country-wide contest,
    from its `areas` entry
    (without `areas`, its polling districts summed: the okrsok file's
    `units`);
  - the council constituency of a municipality split into several,
    its polling districts summed (the okrsok file's `units`),
    for any contest but that constituency's own council;
  - the polling district of an address or a map pick.

  The turnout meter of a polling district shows its 2022 turnout
  where its figures then are known,
  "≈" and the method in the tooltip where not exactly the same district;
  where they are not known, the 2026 turnout's tooltip says so.
  None for the other units.
  The choice is one for every contest of the ballots,
  kept while browsing places:
  a contest without the unit chosen shows the finest it has
  that is not finer.
  It starts at the whole contest.

### Ran last time

Where the election before the page's
(the next older the site shows of the same kind) is built,
a candidate linked to a candidacy of it for the same office
(the same municipality's mayor or council in any constituency,
the same kraj's president or council,
the President, the NR SR or the European Parliament on any list)
has a grey clock turned back beside the chair (`RanBefore` in `js/ballots.js`;
data.js `ranBefore`).
It is not a filter, unlike the other marks:
a press unfolds a line under the name
with the election by its full name and date (as the title bar names it,
i18n.js `electionName`) and the contest then, elected or not,
the votes and their share of the valid ballots
(of the voters with a valid ballot for a council),
the place among that contest's candidates,
and a link to its card on that election's page (`/<lang>/<slug>/#c=…`);
pressed again, it folds it.
It is a button with `aria-expanded`,
the line a part of the row that does not open the card.
The data come with the area files (`elsewhere`, see build.py),
so nothing of the other election is fetched.

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
  where a plain press shows only them
  (not the clock of [Ran last time](#ran-last-time), which only unfolds).
  The marks that filter are the medal of the elected,
  on a party's list the preference votes' and the substitute's,
  and the research's and the chair's (`MARKS`);
  the filter bar names them, the link keeps them (`fm`),
  and each is a button with `aria-pressed`,
  under the pointer of a button,
  where a badge that only explains itself has the help cursor.
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

Under each counted contest the card shows
where the candidate's votes came from:
the polling districts (else municipalities) with the most of them
and those with the highest share
(of the units with at least 30 valid ballots, where two or more have as many),
only units where the candidate got votes,
and a button that shows the votes on the map.
A municipal or regional contest's polling districts are in the one okrsok
file of its area, which the card ranks;
a country-wide one's (a president's, a party's list's) are in a file per
kraj, so the results rank them instead
([`origins`](results.md#a-country-wide-candidates-polling-districts))
and the card loads none of those files.
The map fits a polling district opened from such a card
once its kraj's file has loaded (mapmode.js `followKnown`).
Each unit's name is a link (`o=` with `d=`, and `n=` for a council
constituency's candidate, whose ballot then shows among the district's):
in the page, it selects the unit as a new history entry,
so Back returns to the card,
shows its ballots at its level (the polling district's or the municipality's,
as pressing that level on them would)
and fits the map to the unit, outlined.
Results already on the map stay, at that level:
the candidate's votes, if shown, show the district among its neighbours;
none are put on the map unasked, as the button beside the lists does that.

Where the person is linked to persons of other elections,
"Candidacies in other elections" lists their candidacies there,
newest election first, each as the line of [Ran last time](#ran-last-time),
with the note that the match is by name, age and municipality or region,
no proof of identity.

Research is done on the latest election's candidates
(the newest regular election).
On another election's card, a person linked to a researched one
is shown that research, cut by the build to the findings
whose source was published before this election's day;
a paragraph says when and for which election (by its full name) it was done,
that none was done for this one,
and how many undated findings are left out.
The marks, their filters and the serious-controversies alert
count only those findings.
A candidate not linked to one of the latest election is
"not researched", with that reason.

### Results on the map from the ballots

Every counted contest's header,
on the ballots of a place, on a candidate card and in Favourites,
has two outlined buttons that put its results on the map,
each pressed again to take them off
and tinted, edged in its colour, while the map shows them
(`js/mapmode.js`):

- `WinnerMapButton`, once the candidates' votes are in:
  who got the most votes where,
  with the folded map of results (icons.js `MapResultsIcon`),
  in the results' green;
  a party's row has one too, before its votes' button,
  where its list's results have `areas` per municipality:
  whose preference votes on the list were the most where;
- `TurnoutMapButton`, the turnout meter itself
  beside the ballot box of the turnout menu (icons.js `TurnoutIcon`):
  the contest's turnout over its area,
  in the colour the area is drawn in.

A counted candidate's (party's, answer's) row ends in a square button
with the same ballot box (icons.js `TurnoutIcon`),
which shows the candidate's votes;
a person on a party's list has it only where the list's results
have `areas` per municipality (their preference votes there).
The buttons that are an icon alone are outlined squares of one size,
36 px in a header, 26 px on a row (app.css `--square`),
never shrunk by a long name beside them nor stretched to the row's height;
only the turnout's, with its figures, is wider.
The folded map is kept for a breakdown, several values per area
(whose votes were the most);
a single value per area (a share, a turnout) has a ballot box,
so that the icon says what the map will show.
A pin stands for a place only (the selected one on the map).

The level the ballots show the results at
(`ScopeChoice`: the whole contest or the place's kraj, okres,
regional constituency, obec, council obvod or okrsok;
one choice for all their contests,
kept from place to place, mapmode.js `useLevel`)
is the map's level too, with results on the map or without:

- **The units** of the results on the map follow the zoom at every level
  (see [Results on the map](#results-on-the-map)):
  at the okres level the municipalities keep their own colours and values
  once the zoom draws them.
- **The outline.**
  The map outlines the level's unit of the selected place
  in ink (`--map-level`, 2 px) and veils the rest of the map,
  its fills and borders, not its labels
  (`--map-level-veil`: light grey in the light theme, dark in the dark;
  draw.js `setLevel`, `drawScope`);
  nothing at the whole contest.
  It is drawn under the selected place's own highlight:
  where that outlines the same unit
  (the municipality in the accent colour,
  its council constituency or polling district at the zooms that draw them),
  its colour covers the ink and the two read as one;
  inside a larger unit (a kraj, an okres)
  the selected municipality keeps its accent outline.
  An okrsok or council obvod the place has none of known
  (or an okrsok not drawn: its municipality's okrsky are not,
  or it has no area or no territory, draw.js `scopeOf`)
  falls back to the next coarser unit it has.
- **Choosing a level** fits the view to that unit, zooming in or out
  (map.js `fitUnit`, draw.js `unitBox`),
  or at the whole contest to the contest's area
  (a country-wide contest's: the whole country, as the first view);
  the unit and the area are those of the contest whose choice was pressed,
  as its ballot shows them, the same in every kind of election and
  whatever the map shows (on a town's ballots, the governor's whole
  contest is the kraj even with the mayor's results on the map);
  the results on the map, where they are a contest's,
  move to the same candidate (turnout, winners) at the new level
  (mapmode.js `followLevel`).
- **Results put on the map** carry the level they were put there at
  (the mode's `level`, in the link as `mr=candidate:nrsr:SK%233,okrsok`;
  a link without one is the whole; from the candidate card and the menus,
  the whole); a link's level is the ballots' again when it is opened.
  The view is fitted when they become another contest's
  or another level's (from none, a turnout layer or another contest)
  as a choice of the level would fit it,
  not when they switch between its candidates, its turnout
  and who got the most votes, nor as zooming changes their units.
  A link that names its view keeps it.

The place stays selected, its ballots and the list as they are.

## Favourites

Favourites (`js/favourites.js`) lists every circled candidate's contest
the same way, the circled first
(a country-wide election's under its kind).
Buttons by its title copy a link to them and the filter alone,
with the list open,
or show that link as a large QR code in a dialog of its own,
for another device's camera
(the encoder, `vendor/qrcode-generator.module.js`, loads on first use).

It opens only with its button:

- **From 960 px wide**, as a pane of its own beside the first,
  as the search results are, as wide as the page allows.
  A candidate chosen opens in the first pane,
  and a map click or a contest's results put on the map keep the list open,
  but a place found by the search closes it, as it would hide that place.
- **Narrower**, it is what the pane shows,
  as wide as the page allows on a tablet;
  a phone's sheet leaves the place in view above the list.

## Overview

The ballots of a party-list election (NR SR, EP) or a referendum
are the same everywhere,
so they have an overview as wide as the page allows
(`js/overview.js`, `kinds.js` `overviewKind`),
opened by a button before the contests
(a referendum's with several questions only),
of the parties' lists by one under each list,
and from the map's ballot-box menu without a place
([Map layers](#controls)).
The button before the contests and the menu's box are one toggle
(app.js `overview`): pressed and ticked while the overview shows,
a second press closes it, and either says so after the other was used.
Opened from the menu, the overview leaves the focus where it was,
so that the menu stays open with its box ticked
(on a phone the buttons put away stay out too);
opened otherwise, its title takes the focus.
It opens as Favourites do, in their place:
beside the first pane from 960 px, else in the pane.
Its results are the whole country's.

- **Parties' lists.**
  The parties as tiles, as many to a line as fit
  (two on a phone), in the ballots' order (by votes once counted):
  the ballot number to circle or cross out, the logo and short form,
  which selects the party, the seats and votes
  (or, final, greyed with the struck-through person of no seats),
  and its map buttons as on the ballots, the list's facts in tooltips;
  the selected one edged in the primary colour.
  Under them the selected party's list in full (`PartyList` *full*),
  under a header with the row's logo, name, seats or no seats,
  research marks and votes,
  straight to its persons, in as many columns of 300 px as fit,
  so that a list of 150 takes a third of the height in three columns.
  The filter bar, circles, crosses and the filter's marks
  work as on the ballots (the same `useRowActions`).
  A party chosen whose list starts out of view scrolls it into view.
- **Referendum.**
  Its questions side by side,
  each the contest of the ballots (wording, verdict, answers).

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
  Each vertex has the zoom level from which it is drawn
  (Douglas–Peucker per arc, at 0.3 px):
  a file serves several levels,
  and at the lower ones its vertices crowd closer than a pixel,
  so a level's paths leave those out
  (a drawing of the whole country takes a quarter less time, on a phone half).
- **Neighbours.**
  The countries around Slovakia are drawn below it, duller,
  with dashed borders and their names where most of each shows.
  They cannot be clicked,
  and the lowest zoom keeps every view within them.
- **Borders.**
  Areas are only filled;
  every border is stroked once from the topology,
  in the style of the highest boundary it is part of:
  an obec or okres border under a regional or city obvod border
  drawn too is left to that wider stroke.
  A dashed one is cut into its dashes only where the drawing shows it
  (the canvas would dash it whole, far beyond the view when zoomed in),
  each dash with square ends, as long as round caps would make it:
  thousands of round caps cost twice as much.
- **Zoom** is continuous (`js/zoom.js`):
  wheel, trackpad, pinch, buttons and double-click
  scale the canvas every frame.
  While a pan or zoom goes on,
  the view is drawn again at a lower resolution
  whenever the last drawing no longer covers it,
  and sharp once the gesture settles;
  what has not loaded yet is added as it comes.
  A view asked for again unchanged (the end of a pan after its last move,
  a resize told twice) is not drawn again (`js/map.js` `request`).
- **Touchpad.**
  A pinch reaches the page as ctrl + wheel,
  and the map's scale follows the spread of the fingers,
  as with a pinch on a touch screen,
  equally fast both ways:
  Chromium makes each event's deltaY −100 ln(the scale's change);
  Firefox (except on macOS) 100 × (the last − the current scale),
  the scales measured from the pinch's start,
  which read as Chromium's zoomed out to half the spread
  half as far as in to twice it.
  `zoom.js` follows Firefox's scale
  from a pinch's first event (deltaY −0.1) to its last (0).
  Two fingers moved over the map zoom with their upright travel,
  as a wheel does, and the map keeps every wheel event,
  sideways ones too:
  over the map a sideways swipe is not the browser's back and forward,
  so that a zoom begun a little askew never leaves the place shown.
  Over the panes and the About dialog it is:
  their scrolling is contained only upright (`overscroll-behavior-y`),
  since `contain` both ways ends a sideways swipe there too.

### Base map

A faint base map helps find a neighbourhood
(`base/`, built by `ems basemap` from the election's OpenStreetMap
extract, once for every election on it; no tiles from other servers):
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
  While the map shows results, the waters are opaque instead,
  in the colour they have on the bare land,
  so that the colours stop at the shore:
  a faint lake would take on the colour of the unit under it,
  a bluish shade that reads as another value or candidate.
  The borders and labels still cross a lake,
  and a click in one still picks the unit it is in.
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
- Polling districts with results of their own that the map does not draw
  are buttons on the ballots of their municipality, after its notices
  (ballots.js `UnmappedOkrsky`, "Polling districts not on the map",
  each its number):
  all of a municipality that voted in several but whose are not drawn
  (`okrsky_unknown`, Michalovce in 2017),
  one without an area (addressless) of a municipality whose others are,
  and the special ones without territory
  (`data/index.json` `special`; an icon badge for a prison's
  or a COVID-19 special one, with what it is in the tooltip).
  A municipality of one polling district with territory is drawn as that one,
  so only its special ones are listed.
  The numbers are those the final results' okrsok files of the ballots'
  contests have for the municipality (live.js `obecOkrsky`,
  the files the ballots load anyway; a party's list's left out),
  less those drawn (`geo/index.json` `okrsky.drawn`),
  so none show before the final results, nor while those files load.
  A press picks the polling district as a click on the map picks a drawn one
  (`d` in the hash, with `n`, the council constituency whose council
  counted it, where the municipality has several)
  and shows the ballots at its level, as a polling district opened from
  the candidate card does (app.js `openUnit`);
  having no shape, it outlines and fits its municipality
  (draw.js `scopeOf`).
  The button of the one shown is pressed; a press goes back to the whole
  municipality, as does Back.

### Results on the map

The election's results can colour the map (`js/mapmode.js`).
A candidate is a person, a party (of a party-list election)
or an answer (of a referendum).
What it shows:

- **A candidate's share** of the votes by area,
  from the button at the end of their row,
  which also fits the map to the contest's area:
  across its areas where it spans several
  (a regional contest,
  or Bratislava's or Košice's city contests by city district,
  a country-wide contest),
  else over its one area
  (a mayor's municipality,
  a council's municipality or council constituency,
  in the strongest step, there being nothing to compare it with).
  A person on a party's list has their preference votes
  as a share of the party's votes there.
  A candidate who stood for the same office at the contest's election
  before has a choice of years in the legend ("2026 | 2022",
  "2022 | 2017" for 2022's regional contests;
  `YearChoice` in `js/mapmode.js`):
  the earlier year colours their share then on the units of the page's
  election (see [The election before](#the-election-before)).
- **The turnout**, from the ballot-box menu once counting has started
  (`turnoutChoices`):
  of a regular election, those of them some municipality elects in
  (data.js `electsAnywhere`: 2017 the regional ones alone,
  2018 the municipal and the two cities'):
  - of the municipal elections
    (each municipality,
    and each district of Bratislava and Košice,
    by its own mayor and council: the results' `turnout.json`);
  - of the two cities' own elections of a city mayor and council,
    on ballots of their own
    (the city files; by district where the mayor's contest has them,
    else the city alike);
  - or of the regional elections;

  of a by-election, those of them held somewhere;
  of a country-wide election, its contests' as `turnout:<contest>`:
  each round of a presidential election,
  a referendum once (by its first question),
  a party-list election once (by its party contest).
- **Where a by-election is held**, without results shown:
  its places tinted in the accent colour,
  the okresy holding them lighter when zoomed out,
  with a legend "Where elections are held" and their counts
  (`HELD`, strings `mapmode.held_*`);
  the tooltips name the place and its contests.
  It goes by the units of the zoom as the turnout does
  (data.js `heldObce`):
  each unit drawn is tinted where something is elected in it,
  below 9.5 an okres, from there a municipality,
  and from 11 a municipality electing only some of its council
  constituencies by those alone, its others drawn as places
  without a vote (Ilava's constituency 2 on 2025-09-06);
  the land between them is the same at every zoom from 9.5.
- **The leader.**
  Every contest, once its candidates' votes are in,
  has a button before its turnout
  that colours each unit by the candidate with the most votes there
  (for a council of several seats its top candidate, not those elected,
  as the legend says; a party, an answer, a list's person
  by preference votes),
  in a colour of each candidate's own
  (`--map-series-*`, the eight with the most votes overall,
  the others in grey),
  and labels it with their surname (a party's short form).
  A tie for the most votes is striped diagonally
  in the colours of all those tied,
  stripes a few screen pixels wide at every zoom,
  and labelled with their surnames joined by " / "
  (the tooltip lists their full names).
  The legend lists the candidates with the number of the finest units
  each leads, a tie counting for each of those tied
  (their colour is in its stripes; the count's tooltip says how many are ties),
  and, where the map has stripes, a "Tied" entry
  with a striped swatch and the number of the finest units tied.

**Units by zoom.**
The units follow the zoom, as the boundary overlays do,
each as fine as its figures go:

| Zoom | Units |
|---|---|
| below 9.5 (the municipalities' zoom) | each regional constituency, or where there are none (a by-election, a municipal election alone, a country-wide contest) each okres, as the results have it summed: a regional president's, a city contest's or a country-wide contest's `units` (of the election before, `past` `units`), a regional council constituency's own figures, a turnout's `turnout.json`; none for a contest of one municipality |
| from 9.5 | each municipality by its own figure |
| from 11, where the council constituencies' borders begin | a municipality's council constituencies by theirs |
| from 13, where the polling districts' borders begin | every polling district by its own figure |

- A council constituency's figure is the council's own,
  or for any other contest its polling districts summed per constituency
  (the okrsok file's `units`, grouped by the municipal council
  contests' polling districts, also for the regional contests).
- Polling districts come from the final results' okrsok files
  (`okrsky/<area>.json`, of a country-wide contest
  `okrsky/country/<kraj>.json`, of a party's list
  `okrsky/list/<p>/<kraj>.json`, of the kraje with okrsky drawn;
  fetched only while something shows them);
  an okrsok without an area (addressless) is not one,
  nor is a special okrsok without territory
  (`data/index.json` `special`: a COVID-19 special okrsok of the 2023
  referendum, a prison's): never drawn, it neither shades the map
  nor widens a turnout scale (its 100 % would),
  its figures staying in its municipality's.
  The ballots name each in a notice (summary "Polling district No. 33
  not on the map": its kind, okres or facility and registered voters,
  with the source linked) and have a button that shows its results
  ([Polling districts](#polling-districts)), and the tooltips of the
  municipality and its polling districts list the numbers not drawn
  (`mapmode.tip_special`).
- A municipality without finer figures keeps its own at every zoom,
  and a council constituency's own contest colours its constituency
  at every zoom, the municipality having no figure of it;
  whatever the council overlay draws it in
  (a municipality without a council election may elect its mayor
  or vote in the regional contests).
- A by-election's municipality whose council constituencies have
  figures (the results' `turnout` `councils`;
  on the map of where it is held, its constituencies held)
  is drawn by those alone from their zoom:
  its other constituencies elect no one
  and are drawn as a municipality without a council election is
  (the council overlay's grey), unlabelled,
  not in the municipality's colour
  (Divina's 2 and 3 on 2026-03-21);
  pointing at one says no vote is held there;
  likewise a constituency held nowhere for want of candidates
  ([Uncontested contests](#uncontested-contests)).
- The council overlay greys a municipality of the election
  without a council election;
  of a by-election, only where it is held (map.js `setOverlays`):
  the rest of the country is no part of it and stays land.
- These thresholds hold whether the overlays are on or not
  (draw.js `showsUnits`).

**Colours.**
Each unit takes one of six steps of a colour:
a candidate's votes the results' green (`--map-result-*`);
a turnout the colour its area is drawn in, mixed into the land:
the municipalities' red, a council constituency's orange,
the cities' green, a regional contest's violet.
A country-wide contest (president, referendum, National Council,
European Parliament), the only turnout of its election,
has an indigo of its own (`--map-turnout`)
on the map, the legend, the ballots' turnout button
and the ballot-box menu's icon:
not the state border's slate,
since the map's greys mean muted or missing
(the level's veil, no result, no election held).
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
For a candidate who stood in 2022 it has the choice of years,
on a phone's sheet always in view.

The legend folds on every screen into a pill
(`.map-legend.pill`) with its title and the overall figure
("Most votes" and "Smer-SD 22.9 %"),
itself the button that unfolds it again (`aria-expanded`);
folding leaves the results on the map,
which only the separate × button takes off.
The choice is one for every map mode and is kept
in `localStorage` (`election-map-slovakia.legend`, mapmode.js
`storedFold`), so another candidate, a turnout or a reload
keeps the legend folded until it is unfolded;
until the visitor chooses, it starts whole,
and folded on a phone.
There the pill sits under the search card
and counts in the map's insets (app.js `insets`);
with the sheet open, folded is the bar's short form
(title, figure, scale or chips),
unfolded adds the subtitle, the units and the estimated districts.

**Pointing.**
With a mouse, pointing at the coloured map names the unit
whose colour is under the pointer
(a regional constituency, municipality, council constituency
or polling district) with its figures;
a polling district or municipality also with those of 2022
where anything is known of them:
"2022 (same area)" or another method label,
the turnout then,
and on a candidate's map their votes then,
on a leader's map the leader's
("Name: 38 % · 120 of 316").
Where the polling districts changed beyond matching,
one line: "2022 (not known: polling districts changed)".
On a touch screen a tap shows the same in a card.

### The election before

The figures of the election before on the polling districts of the page's
come from the okrsok files' `past`
([results.md](results.md#okrskyareajson)).
That is each contest's own, the newest earlier election that held its kind:
2022 for every contest of 2026, but for 2022's
the municipal elections of 2018 for its municipal contests
and the regional ones of 2017 for its regional contests
(held apart then).
So every figure of it, on the ballots and on the map,
is labelled with the year of its own file's `past` `day`
(mapmode.js `figures` `then` for a candidate's map, its legend and year
buttons), not with the page's `previous`.
Each okrsok's are labelled by how they were found
(live.js `PAST`, `pastLabel` and `pastTitle`, strings `past.*`):

| Method | Label | Meaning (`past.how_*`) |
|---|---|---|
| same | same area | the same addresses, or the whole municipality as its only district |
| identity | same polling district number, about as many voters | number unchanged, registered voters within 10 % |
| approximate | estimated: polling districts changed | weighted by the share of its addresses in each district then |
| unknown | not known: polling districts changed | no figures are shown |

A candidate's map of the election before (`gatherPrevious`) colours
each municipality by its own figures then where the contest covers all of it,
each drawn polling district by its own,
a council constituency of a municipality split into several
by its polling districts summed (none where one is not known;
summed with the results, the okrsok files' `past` `units`),
and a regional constituency, or an okres, as the results have it summed
(`past` `units`: `zsk`, `okres`, a regional council constituency's `obce`);
the total is the contest's own then, else its municipalities' summed
where all are known (`obce`);
a candidate absent from a unit's ballot then has no figure there.
The steps are the 2026 map's green;
a polling district estimated from addresses
is hatched with the land (`PREVIOUS_PALETTE`, draw.js `stepFill` stripes),
one not known is grey (`--map-past-unknown`) and labelled "?".
Below the scale, the legend lists both with a swatch
and how many drawn polling districts each is,
each with its explanation as the tooltip.

## The URL hash

The selected place, candidate, Favourites, the overview
(`ov`, `ov=<n>` with party *n*'s list) and the About dialog
are kept in the URL hash, so links can be shared.
So are the circled candidates and the filter,
and what the map shows, so that a link opens the same view
(`js/app.js`):

- `m=zoom/lat/lon`, the view, once it has moved from the first one
  (written when the map has stood still for 0.4 s,
  as browsers throttle history writes);
- `h`, the layers switched off, comma-separated
  (`zsk`, `city`, `oz`, `okrsky` of those the election has,
  `base`, `buildings`);
- `mr`, the results on the map (mapmode.js `formatMode`):
  `turnout:municipal|city|regional`, `turnout:<contest>`,
  `winner:<contest>`, `candidate:<candidacy>`
  or `previous:<candidacy>` (their votes at the election before),
  for every contest id
  (`mr=turnout:prezident:SK/2`, `mr=candidate:nrsr:SK/12%233`:
  `#` is written `%23`).

`k`, the circled candidates, mirrors the ballot
(`<contest>.<numbers>`): `nrsr:SK.12` circles party 12,
`nrsr:SK/12.3.7` positions 3 and 7 on its list.

A link with a view opens on it,
not on the place it selects nor on the area of the results it shows.
Back and Forward leave all these as they are:
only a link typed or pasted into the address bar brings its own.
Examples are in [testing.md](testing.md#the-site-locally-with-results).

## About dialog

The About dialog (`js/about.js`) is a short page:
a sentence on the site, its elections since the year of the oldest
(`about.lead`);
then, under the page's election's name (`electionName`),
what its page offers, a bulleted line each beside the icon the app gives
the thing elsewhere (`FEATURES`, `about.feature.<item>`), chosen by kind:
where to find one's ballots, or the results where one votes,
or for by-elections where they are held (map);
what the ballot holds (the kind's icon): the candidates and their parties,
of a president also age, occupation and residence,
the parties' lists, or a referendum's questions;
what the results are (ballot box);
who held each office, where it is known (chair);
the research and its limits (magnifier) and Favourites (heart),
but for a referendum;
no ads and no tracking (struck eye).
Under the list, a link to each section by its title
(`#v=about-method`, `-sources`, `-research`, `-disclaimers`);
then the version (a link to its GitHub release), the source code
and the licence.
The shell's `<noscript>` paragraph and the page description
(`app.features.<kind>`, `app.description.<kind>`) stay sentences,
for search engines and visitors without JavaScript.
Its lists come from the election's data/about.json:
the sources are those the page's election reads, and those no
election names (the countries around).
The method section ends with the municipalities whose council
constituencies or polling districts another vote's borders stand in for
(data/about.json `stand_ins`), one line per kind of unit and vote, named
as above, earlier or later (`about.method.obvody_adopted`, `okrsky_adopted`).
On the page of an election other than the latest
a section `#v=about-latest`,
"What comes from 2026",
lists each datum taken from the latest election and each one missing,
with counts (data/about.json `substitutes`):
the boundaries and the municipalities whose boundary differed,
the council constituencies drawn from the election's own documents,
with the latest's rules proven to match (naming those municipalities),
or not known,
the polling districts drawn, taken from elsewhere or not known,
and of either those from documents dated only approximately
or partly from a later source,
the candidates linked, the research (its own where its candidates were
researched, `about.latest.research_own`, else that reused and the
findings left out),
and that the base map and the addresses are the election's own.

## Results and caching

The site makes requests only to its own parts, the election results included:
the app fetches the election's bundles and base map (the shell's config
`map`, `data` and `base`)
and its results, the directory of the election's day
in the results part (the shell's config `results`)
or, where that has no `status.json` yet and the election has `live`,
in the live part (`live`), every minute within `liveWindow`;
`js/live.js` reads its `status.json` and the files it names,
each from the directory of the `status.json` that lists it,
and goes back to the final results once they are there
([results.md](results.md)).
A file is fetched when something first shows its figures
(a place's ballots, the map, the card)
and shown as soon as it comes, without another click:
what asked for it listens from the commit of its first render
(`useLive`, a layout effect),
so one that comes quickly (a small one, or one the browser has kept)
is not missed.
Every page of the app carries a Content-Security-Policy `<meta>`,
the first thing of its `<head>` that loads anything
(build.py `page_policy`):
a shell's connect-src is `'self'`
and the origins of the deployed bundles, base maps and results alone,
the live results' where an election reads them,
so the browser enforces this;
the picker's and the 404 page's is `'self'` alone.
The app's `_headers`, from `web/_headers`,
adds what is the same for every page,
`frame-ancestors` among it, which a `<meta>` cannot carry,
and no default-src or connect-src, since a browser enforces both policies.
The origins are not in the header itself:
a deployed app names dozens,
more than a `_headers` line may hold (2,000 characters).
`ems serve` serves the parts as one site:
the app at `/`, the bundles at `/map/<slug>/` and `/data/<slug>/`,
the base maps at `/base/<extract>/`,
the final results at `/results/`, the live results at `/live/`
and the cached copies at `/cache/`,
each with the headers of its own part.

Code, libraries and images are under their versioned directories,
kept by browsers for good.
Every JSON file of the election is fetched with `?v=` and the version of
its bundle or base map
(`mapVersion`, `dataVersion` or `baseVersion` in the shell's config;
`dataUrl` in `js/files.js`), the UI strings with the strings version
(`stringsVersion`, a hash of them alone, shared by every election;
`sharedUrl`),
the results' files with the hash `status.json` gives them, kept a day,
and `status.json` revalidated on every load.
So a release reaches visitors on their next page load
(`build.py`, "Cache busting";
[deploy.md](deploy.md#caching)).
