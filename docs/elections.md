# Adding an election

Instructions for an AI agent (or a person)
asked to add one election to the site:
a past one, to examine its results,
or an upcoming one, to show its candidates and later its results.
The site shows elections of six kinds
(`kind` in `config/elections.toml`):

| Kind | What | Contests (`src/election_map_slovakia/contests.py`) |
|---|---|---|
| `municipal-regional` | the regular municipal and regional elections, held together every four years | mayors, councils, regional presidents and councils |
| `by-election` | municipal (or regional) by-elections and new elections, held on one day in some places only | the same, only where held |
| `presidential` | the President, in one or two rounds | `prezident:SK/1`, `prezident:SK/2` |
| `referendum` | a national referendum of one or more questions | `referendum:SK/<question>` |
| `parliament` | the National Council (NR SR) | the parties `nrsr:SK`, each party's list `nrsr:SK/<party>` |
| `european` | the European Parliament | the parties `ep:SK`, each party's list `ep:SK/<party>` |

The work is data and configuration only:
the code reads every kind.
Never invent a figure, a name or a source:
everything comes from an official file pinned as an input,
or is transcribed into the curated data with its source named.
Researching the candidates is a separate job
([agent-jobs.md](agent-jobs.md#research)), not part of this one.

Read first:
[pipeline.md](pipeline.md) (Elections, `fetch` and the input store, Keys),
the header comments of `config/elections.toml`, `config/inputs.toml`,
`config/parties.toml` and `config/overrides.toml`,
which document every field used below.

## The steps, for every kind

1. **Slug and day.**
   The slug is the election's name in URLs:
   a digit, then lowercase letters, digits and dashes.
   `2026` for a regular election,
   `<year>-<month>` for a by-election (`2026-03`),
   `<year>-<word>` for the others
   (`2024-prezident`, `2023-referendum`, `2023-nrsr`, `2024-ep`).
   No two elections may share a day:
   the build and results directories are keyed by it
   (`data/curated/elections/<day>/`, `data/build/<day>/`).
2. **Sources.**
   Find the official files (per kind below)
   on the Statistical Office's election sites
   (`https://volby.statistics.sk/<kind>/<kind><year>/`,
   also `https://www.volbysr.sk/`)
   and on the Ministry of Interior's (`https://www.minv.sk/?volby`).
   Their pages list the files for download
   (`json/downloadSK.json` beside a results page names every table).
   Prefer, per table, what the readers take:
   CSV with full Slovak column names (comma-separated, quoted)
   or XLSX; an old election's CSV with coded headers (`OBEC|OKRSOK|P_ANO`,
   the referendum of 2023) is not read: take its XLSX tables instead.
3. **Inputs.**
   Add each file to `config/inputs.toml` as `[input.<name>]`,
   the name ending in the year its data are of
   (`results-oso2022`, `osm-slovakia-2026`, `zsk-obvody-ba-2026`),
   with `url`, `file`, `kind`, and `expect` for a CSV or `members` for a zip,
   as the file's header comment explains;
   then `uv run ems inputs update <name>...`,
   which downloads, checks and pins it (`sha256`, `retrieved`).
   A whole package (a zip of every table) or the single tables both work:
   the readers find a table by its id (`tab03e`) in either.
   `uv run ems inputs publish` then uploads the pinned files
   to the input store; it needs the GitHub CLI logged in
   with write access to the repository's releases,
   so leave it to the owner if you have none, and say so.
4. **The election's table** in `config/elections.toml`
   (per kind below), with the map inputs:
   `zbgis` (the three ZBGIS levels), `osm` and `addresses`.
   Use those of the newest election unless the election has its own.
   The elections on one `osm` extract share its base map,
   which is cut by ZBGIS levels 1 and 0:
   they must name the same first two `zbgis` levels
   (loading the configuration fails otherwise).
   An election drawn on a later election's boundaries
   (every past election added now: ZBGIS serves today's boundaries)
   needs
   - `as_of` on its `osm` and `addresses` inputs
     (the date their data are of; the map's credits name it);
   - `data/curated/elections/<day>/boundaries.toml`,
     how the boundaries it is drawn on differ from its own
     (see the 2022 election's: `compared`, `used` and a `[[change]]`
     per obec whose land moved by more than redrawing; none where
     nothing did).
5. **Overrides**, `[election.<slug>]` in `config/overrides.toml`:
   at least the address register's two military districts
   (`[election.<slug>.address]`, as the other elections have them);
   `ems candidates` and `ems addresses` name any other name they cannot
   match, to be added there.
6. **Parties**, `config/parties.toml`:
   every party and ballot subject as the lists write it
   (`short`, `name`, a logo per slug only with a licence that allows it);
   a coalition standing as one subject lists its parties in `members`,
   which sets its threshold.
   `ems build` fails naming each one missing.
7. **Okrsky** (optional).
   With `units` (the territorial division: ŠÚ SR's `tab0dd` as XLSX,
   or the table of a country-wide election's package, format `volbysr`)
   the okrsky are counted;
   they are drawn on the map only where the election's curated data
   have their rules (`okrsok-rules` jobs, [agent-jobs.md](agent-jobs.md)),
   so without them the map's finest unit is the municipality.
   A country-wide election or a by-election takes them from the regular
   elections where they provably match, after its results are built,
   and elsewhere the nearest vote's own as a stand-in, indicative only:
   `uv run ems job reuse --election <slug>`
   ([agent-jobs.md](agent-jobs.md#a-country-wide-election-or-a-by-election)),
   then `uv run ems make` again;
   `okrsok-rules` jobs then look for the election's own documents,
   which replace the copies where found.
   The results per okrsok are kept either way.
8. **Build.**
   `uv run ems make --election <slug>`, then `uv run ems make`.
   A table that lacks a column read from it fails
   naming the table, the columns wanted and the columns it has:
   where ŠÚ SR merely words a column differently,
   add the wording to the aliases in `src/election_map_slovakia/lists.py`
   (candidate lists) or `national.py` (results),
   with a test in `tests/test_lists.py` or `tests/test_national.py`.
   Look at the election's pages ([testing.md](testing.md)):
   its candidates, the results on the ballots and on the map.
9. **Lock and deploy.**
   `uv run ems data lock`, and commit
   `config/`, `data/curated/elections/<day>/` and `data/published.toml`.
   A new election needs two new Pages projects,
   `ems-map-<slug>` and `ems-data-<slug>`
   ([deploy.md](deploy.md), setup step 6),
   created before the release:
   `uv run ems data projects --create`,
   or ask the owner to run it where you lack the Cloudflare login.

## Presidential

- **Sources.**
  `https://volby.statistics.sk/prez/prez<year>/`,
  a package per round (2024: `files/kolo1/`, `files/kolo2/`, CSV;
  2019: `files/PRE_2019_KOLO<n>_xlsx.zip`, XLSX only):
  the candidates are each round's `tab0a`
  (`Poradie na hlasovacom lístku`, `Meno`, `Priezvisko`, `Titul`, `Vek`,
  `Zamestnanie`, `Obec` or `Obec trvalého pobytu`, `Poznámka`,
  `X` = withdrew), the territorial division round 1's `tab0b` (2024)
  or `tab0c` (2019), the results the round's package
  (`tab01`, `tab02d`, `tab02e`, `tab03a`, `tab03e`, `tab03f`).
- **Configuration**
  (as the elections of 2019 and 2024 in `config/elections.toml`):

  ```toml
  [election.2024-prezident]
  day = 2024-03-23            # round 1
  kind = "presidential"
  second_round = 2024-04-06   # once called: after round 1 elected nobody
  polls_open = 07:00:00
  polls_close = 22:00:00
  live = false
  live_days = 7
  units = { format = "volbysr", input = "results-prez2024-1", table = "tab0b" }
  candidates = { format = "volbysr", round1 = "results-prez2024-1", round2 = "results-prez2024-2" }
  results = { format = "volbysr", inputs = ["results-prez2024-1", "results-prez2024-2"] }
  # addresses, zbgis, osm, records as for every election
  ```
- **Before the election** only round 1 is known:
  no `second_round`, no `round2`, no `results`.
  After round 1, add the results of round 1;
  once round 2 is called, `second_round` and its candidate list;
  after it, its results.
  A candidate in both rounds is one person,
  merged on name, residence and age:
  one who has a birthday between the rounds
  (Ivan Korčok in 2024) needs a `person.merge` in `config/overrides.toml`;
  `ems candidates` reports the persons with two candidacies.
- Round 1 elects a candidate with more than half
  of the eligible voters' votes;
  otherwise the two best go on to round 2,
  which the one with more votes wins.
  The results read who was elected or went on
  from the tables' notes (`zvolený`, `postupujúci`, or `P` in 2024),
  else from the votes.
- **Research**, a separate job:
  `uv run ems job make research --election <slug> --only sk --size 1`
  ([agent-jobs.md](agent-jobs.md#research)); for an election past,
  only pages published before its day count.

## Referendum

- **Sources.**
  The questions' wording: the President's decision calling the referendum
  (Zbierka zákonov, or `tab0a` of the results package,
  "Otázka predložená na rozhodnutie v referende").
  Results: `https://volby.statistics.sk/ref/ref<year>/`;
  take the XLSX tables where its CSV ones are coded.
- **Configuration.**

  ```toml
  [election.2023-referendum]
  day = 2023-01-21
  kind = "referendum"
  questions = ["Súhlasíte s tým, že …?"]   # each in full, in order
  results = { format = "volbysr", inputs = ["results-ref2023"] }
  ```

  A referendum has no `candidates`.
- A referendum is valid where more than half of the eligible voters
  took part; a question's answer is adopted
  with more than half of the valid votes.
  The results read yes and no per question
  (`Počet hlasov "ÁNO"`, `Počet hlasov "NIE"`,
  per question where a table has `Číslo otázky`).

## Parliament (NR SR) and European Parliament

- **Sources.**
  `https://volby.statistics.sk/nrsr/nrsr<year>/` or `…/ep/ep<year>/`:
  `tab0a` the ballot subjects (`Číslo politického subjektu`,
  `Názov politického subjektu`, `Skratka politického subjektu`
  (2019–2020 `Oficiálna skratka politického subjektu`),
  `Počet kandidátov`, `Poznámka`),
  `tab0b` their lists (by subject and `Poradie na hlasovacom lístku`,
  with `Obec trvalého pobytu`, for the EP of 2024 `Obec`).
  Both appear on the results site before the election day,
  with the candidates registered;
  until then the Ministry of Interior's lists can be transcribed
  into the curated format (below).
  Results: the package (`tab01`, `tab02d`, `tab02e`, `tab03a`, `tab03e`,
  `tab03f`, `tab04`, `tab06`, `tab07a`, and `tab07e`
  for the preference votes per municipality, which the map of a candidate
  needs). One zip of them all is input enough for the lists and the
  results: a table is read only when a step needs it, and `tab07e` row by
  row (NR SR 2023's is 0.8 GB of CSV, its `tab07f` per okrsok, which no
  step reads, 1.8 GB).
  The packages of 2019–2024 differ:
  a party's seats are in `tab03a` (`Počet získaných mandátov`, empty for
  none), else in `tab04`;
  the place after the preference votes is in `tab07a` from 2023 on
  (`Poradie po zohľadnení prednostného hlasovania`, empty on a list
  without seats), before that the elected are those of `tab06`;
  `tab07e` is a row per municipality and person, but in NR SR 2020's XLSX
  a worksheet per subject (`…_tab07e_PS<n>`), a row per municipality
  where it has votes and a column per person (`1. Jozef Sásik`);
  NR SR 2020's CSV package lacks most tables (`tab07e` among them):
  use the XLSX one.
  EP 2019's tables per municipality and okrsok word their voters
  `Počet vydaných obálok` and their valid votes `Počet platných hlasov`.
- **Configuration.**

  ```toml
  [election.2023-nrsr]
  day = 2023-09-30
  kind = "parliament"          # "european" for the EP
  seats = 150                  # EP: 14 (2019), 15 (2024)
  threshold = 5.0
  coalition_thresholds = [[2, 7.0], [4, 10.0]]   # EP: none
  preferences = 4              # EP: 2
  preference_quota = 3.0       # EP: 3.0 as well
  candidates = { format = "volbysr", subjects = "results-nrsr2023", candidates = "results-nrsr2023" }
  results = { format = "volbysr", inputs = ["results-nrsr2023"] }
  ```

  Check every value against the law in force for that election
  (Act No. 180/2014 Coll. on the conditions of the exercise of
  the right to vote, as amended, slov-lex.sk's version of the day:
  NR SR § 66 ods. 2 the thresholds, § 58 the four marks, § 68 ods. 5 the
  quota; EP § 93 ods. 2 one threshold for parties and coalitions alike,
  § 87 the two marks, § 94 ods. 5 the quota; the EP's seats by the
  European Council's decision for that term, which ŠÚ SR's `tab04x`
  repeats) and say in a comment where it comes from.
  Of the EP's 14 seats of 2019 one was taken up only after Brexit
  (1 February 2020); ŠÚ SR allotted all 14.
- Each subject's party name must be in `config/parties.toml`;
  a coalition's entry lists its `members`. A coalition is what MV SR
  registered as one: a party that puts other parties' members on its list
  under a name naming them (OĽANO in 2020) is no coalition.

## Regular elections before 2022

- Until 2018 the municipal and the regional elections were held on days
  of their own: the regional on 4 November 2017, the municipal on
  10 November 2018. Each is a regular election (`kind =
  "municipal-regional"`) of one half (`config.Election.halves`): it has
  that half's contests only, its strings are keyed by its label
  (`municipal`, `regional`: `app.title.<label>`, `elections.name.…`,
  `about.purpose.…`), the app offers that half's ballots only and
  compares a candidate with the newest earlier election holding the
  contest's half.
- **Sources.** ŠÚ SR's XLSX packages:
  `https://volby.statistics.sk/osk/osk2017/files/OSK_2017_xlsx.zip`;
  `https://volby.statistics.sk/oso/oso2018/files/OSO_2018_xlsx.zip`
  with `OSO_2018_okrsky-xlsx.zip` (the tables per okrsok).
  The 2018 package lists every council candidate only where ŠÚ SR
  counted the obec per okrsok; elsewhere the elected only
  (`elected_only`), and no candidate has an age: they are linked to the
  other elections by `config/links.toml` only.
- **Configuration** (`statoffice.py` reads both; the territorial division
  is a table of the package):

  ```toml
  [election.2018]
  day = 2018-11-10
  kind = "municipal-regional"
  units = { format = "volbysr", input = "results-oso2018", table = "tab02bd" }
  candidates = { format = "susr", oso = "results-oso2018", okrsky = "results-oso2018-okrsky" }
  results = { format = "susr", inputs = ["results-oso2018", "results-oso2018-okrsky"] }

  [election.2017]
  day = 2017-11-04
  kind = "municipal-regional"
  units = { format = "volbysr", input = "results-osk2017", table = "tab0dc" }
  candidates = { format = "susr", osk = "results-osk2017" }
  results = { format = "susr", inputs = ["results-osk2017"] }
  ```

  `results` names the packages its `susr` candidates do, in their order.
  No `incumbents`: the office holders before are not in the inputs.
- The curated obvody: the cities' councils (2018,
  `obvody/BA.toml`, `KE.toml`) and the regions' (2017,
  `obvody/zsk-<kraj>.toml`, generated from the package's `tab0dc` and
  `tab0db`, the documents pinned as `records`), as for 2022.

## By-elections

- **Sources.**
  `https://volby.statistics.sk/oso/doplnkove<year of the term>/`
  lists the by-elections and new elections of a term
  and publishes a package for each day, with the candidates and the results:
  since 2023 `OSO<yyyymm>_SK_xlsx.zip`
  (the regular elections already pin these packages for their office
  holders: `results-oso<yyyymm>` in `config/inputs.toml`);
  in the term elected in 2018 (2019–2022, `doplnkove2018/files/`)
  `OSO_<yyyymm>_xlsx.zip`, laid out otherwise
  and with less in it: the mayor candidates without title, age or
  occupation, of the councils only the elected (name and titles in one
  column), the results per obec only (no okrsky).
  Before the election day the candidates are in the municipalities'
  notices (on their websites): transcribe them into the curated format.
- **Configuration**, for a package of either layout
  (the readers tell them apart by its tables):

  ```toml
  [election.2026-03]
  day = 2026-03-21
  kind = "by-election"
  candidates = { format = "susr-by", package = "results-oso202603" }
  results = { format = "susr-by", inputs = ["results-oso202603"] }
  ```

  Before the package exists: `candidates = { format = "curated" }`
  and no `results`.
- **A package of 2019–2022.**
  Its council contests list the elected only,
  numbered in the order they were elected
  (the app says that the others are not published);
  its candidates have no age, so they are linked to no one
  in the other elections but by `config/links.toml`.
  The municipalities' own lists of their registered candidates
  fill that in: transcribed into the election's `candidates.toml`
  ([a supplement](#a-supplement-to-a-by-elections-package)),
  each contest there replaces the package's.
- **New elections and by-elections proper.**
  One day holds both: by-elections proper (doplňujúce voľby) of seats
  of the council elected at the regular election of the term,
  in its obvody, and new elections (nové voľby) of a mayor or a whole
  council, whose obvody may be drawn anew.
  `candidates` tells them apart by the seats
  and marks each contest's `vote`
  ([pipeline.md](pipeline.md#candidates)):
  only a by-election proper takes anything of its term's council.
- A council by-election proper in one obvod of a council of several
  draws that obvod where the election's curated data have the council's
  rule set (`obvody/oz/<obec>.toml`):
  after its results are built,
  `uv run ems job reuse --election <slug>` copies it, with its proofs,
  from the regular election the council was elected in
  ([agent-jobs.md](agent-jobs.md#a-country-wide-election-or-a-by-election)),
  then `uv run ems make` again;
  without it the ballots name the obvod
  without placing addresses in it.
  A council elected anew in several obvody
  has them from its own decision (the `obvod-rules` job asks for it,
  [agent-jobs.md](agent-jobs.md#obvod-rules));
  until then another election's stand in, shown as indicative.
- **Called but not held.**
  Where nobody stood, the package marks the municipality
  "Nekonajú sa" with the council seats called (none: the mayor):
  `candidates` makes those contests uncontested
  ([pipeline.md](pipeline.md#candidates)),
  the council's in the one obvod of the term's council
  (of a council elected anew, in its own one obvod where the package
  counts it).
  The package does not tell a mayor called beside council seats:
  annex 1 of the Speaker's decision calling the by-election
  (slov-lex, "Zoznam obcí, v ktorých sa vyhlasujú voľby…") lists it;
  transcribe it into the election's `uncontested.toml`
  (`src/election_map_slovakia/config.py` `load_uncontested`):

  ```toml
  [[contest]]
  id = "starosta:520080"
  source = "https://static.slov-lex.sk/pdf/prilohy/SK/ZZ/2025/262/vyhlasene_znenie_5769421-2.pdf"
  title = "Rozhodnutie predsedu NR SR č. 262/2025 Z. z., príloha č. 1: Brezovec – starosta, poslanci"
  ```

  The ballots say such a contest was called but not held,
  and it is not among the places where the vote is held.
- A regional by-election (a president or a council obvod of a kraj)
  is read from the curated format only.

## The curated format

`data/curated/elections/<day>/candidates.toml`,
for any kind but a referendum,
where no table can be read:

```toml
[[contest]]
id = "oz:500011/2"      # any contest id of contests.py; a party's list: "nrsr:SK/<number>"
seats = 1               # councils
# party = "…"           # a party's list: its subject's party
source = "https://…"    # optional: the document transcribed (http(s) URL)
date = 2026-09-04       # with source: the date it bears
[[contest.candidate]]
number = 1
title_before = "Ing."   # optional, also title_after
first_name = "Jana"
surname = "Nová"
age = 48
occupation = "učiteľka"
parties = ["…"]         # self-government contests; [] = independent
residence = "Nitra"     # regional, presidential and list candidates
withdrawn = false       # optional

[[subject]]             # parliament and European: the ballot subjects
number = 1
party = "…"
```

`config.load_candidates` checks it and names what is wrong.
Name the documents transcribed in a comment at the top.

### A supplement to a by-election's package

A by-election read from a package of 2019–2022 (`susr-by`)
may have a `candidates.toml` too:
each contest in it replaces the package's list of that contest
with the municipality's own list of its registered candidates
(*zoznam zaregistrovaných kandidátov* for mayor, for the council,
published on the municipality's website or official notice board),
complete and with titles, ages and occupations.
The package's votes and elected go onto it:

- a mayor contest must list exactly the package's candidates,
  each under the package's ballot number;
- a council contest must list every councillor the package has elected
  (matched by name, titles, case and diacritics aside),
  and the others who stood;
- the contest must be one of the package's,
  and its `seats`, if given, the package's.

`ems candidates` fails naming each contest that does not fit.
A contest not in the file keeps the package's list.
Each contest needs `source` and `date`.
Per contest, transcribe exactly:

```toml
# Obec …, okres …: the by-election of 2019-04-13.
[[contest]]
id = "oz:500011/1"      # starosta:<obec> or oz:<obec>/<obvod>, as the package has it
source = "https://…"    # the list itself (PDF or page), or its Internet Archive copy
date = 2019-03-14       # the date the list bears (not after the election)
[[contest.candidate]]
number = 1              # the ballot number the list gives (councils: in alphabetical order)
title_before = "Ing."   # as written, before and after the name; leave out where none
first_name = "Jana"
surname = "Nová"        # every word of it
age = 48                # as the list states it
occupation = "učiteľka" # as written; "" where the list states none
parties = []            # the nominating parties' full names (the package's tab0b,
                        # keys of config/parties.toml); [] = independent
withdrawn = true        # only where the municipality announced the withdrawal
```

Never fill in a candidate, a number or an age the document does not give;
leave a contest out rather than transcribe part of it.

## Upcoming elections

- Add the election with its candidates as soon as they are published;
  leave out `results`.
  Once released, it is the site's front page, `/<lang>/`,
  as the newest election (`Config.home`; a by-election never is:
  it is held in a few places only).
- On the evening and the days after,
  the app reads the live results `ems results poll` writes and deploys
  ([results.md](results.md#a-future-election-night)),
  of the regular elections only (it reads their night files alone),
  so the other kinds show their results once the definitive packages
  are pinned as `results` (step 3) and released.
