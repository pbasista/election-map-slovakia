# Changelog

Notable changes, newest first. The version is set in
`src/election_map_slovakia/__init__.py`; tagging `vX.Y.Z` builds and deploys
it (see [docs/deploy.md](docs/deploy.md)).

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
