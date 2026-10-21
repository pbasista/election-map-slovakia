# Changelog

Notable changes, newest first. The version is set in
`src/election_map_slovakia/__init__.py`; tagging `vX.Y.Z` builds and deploys
it (see [docs/deploy.md](docs/deploy.md)).

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
