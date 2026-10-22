# Changelog

Notable changes, newest first. The version is set in
`src/election_map_slovakia/__init__.py`; tagging `vX.Y.Z` builds and deploys
it (see [docs/deploy.md](docs/deploy.md)).

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
