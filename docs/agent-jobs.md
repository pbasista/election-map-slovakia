# Agent jobs

Work that needs judgement
(translating, reading municipal resolutions, researching candidates)
is done by AI agents through job directories.
`ems job make` writes the jobs, an agent fills in each,
and `ems job ingest` checks the output and merges it into `data/curated/`.

| Kind | What the agent does | Module |
|---|---|---|
| [`translation`](#translation) | translates UI strings, occupations and research | `translate.py` |
| [`obvod-rules`](#obvod-rules) | transcribes a municipality's council obvody by address | `obvodrules.py` |
| [`okrsok-rules`](#okrsok-rules) | transcribes a municipality's okrsky (polling districts) | `okrsokrules.py` |
| [`research`](#research) | researches candidates in allowlisted sources | `research.py` |

The framework is `src/election_map_slovakia/jobs.py`;
the modules are beside it.

## How jobs work

```sh
uv run ems job make translation                 # every job still to do
uv run ems job make translation --only cs ui    # restrict (languages, parts)
uv run ems job make translation --size 500      # items per job
uv run ems job ingest data/jobs/translation-001 # check and merge output.json
```

`ems job make KIND` takes these options:

| Option | Effect |
|---|---|
| `--election DAY` | the election whose work to make (ISO day or slug; default: the latest, the newest `municipal-regional` election), for the kinds that work per election |
| `--only NAME …` | restrict to these; their meaning is the kind's |
| `--size N` | items per job (default: the kind's) |
| `--priority ORDER` | order of the items, if the kind has several |
| `--limit N` | write at most N jobs, the first ones |

`obvod-rules` and `okrsok-rules` work per election:
they read that election's candidate lists and build output
(`data/build/<election day>/`)
and write into its curated data.
They need the election's `units` (the territorial division),
which every regular election has
and a by-election or a country-wide election may lack:
without it they fail naming the election.
Their items are the election's municipalities with several council obvody
or okrsky (`obvod-addresses/`);
a vote other than a regular election
(a country-wide one, a by-election) elects no council or only some of one,
so `okrsok-rules` has its work there
([Another vote](#another-vote)),
besides the okrsky `ems job reuse` copies from the regular elections
([A country-wide election or a by-election](#a-country-wide-election-or-a-by-election)).
`research` works per election too (by default the latest's candidates).
These jobs record the election in `input.json` as `election`, its day,
and ingest uses that election, not the latest;
a job made before jobs recorded their election cannot be ingested
and must be made again.
A job not ingested yet keeps its items out of its own election's jobs only.
An election not researched in its own right gets the findings of its
candidates linked to the latest election's researched ones,
published before its last round's day.
`translation` serves every election at once.

### A job directory

`make` writes `data/jobs/<kind>-NNN/` with:

- `input.json`: the items, and context such as the election;
- `schema.json`: the JSON Schema of the expected `output.json`;
- `prompt.md`: the instructions;
- `README.md`: how to run it.

An agent with only that directory
(and the web, where the prompt needs it)
writes `output.json`.

### Ingest

`ingest` validates `output.json` against the schema
and the kind's deterministic checks,
merges the accepted items into `data/curated/`,
and lists the rejected ones with their reasons in `ingest-report.md`.
Its exit code is 1 if any item was rejected or missing.

- Ingesting again is harmless.
- `ingest` skips a job without `output.json`, which stays pending,
  so `ems job ingest data/jobs/translation-*` can run
  while agents still work.
- Items already curated, or in a job not ingested yet, are not made again.
- Items rejected at ingest go into new jobs the next time `make` runs.

`data/jobs/` is git-ignored scratch;
what is committed is `data/curated/`
([pipeline.md](pipeline.md#curated-data)).

## `translation`

Translates:

- the UI strings, from English with the Slovak for reference,
  one job per language;
- the candidates' occupations of every election, from Slovak,
  most frequent first, about 900 per job,
  into every enabled language but Slovak;
- the research claims (from English)
  and quotes (from the page's language) into the other languages.

**Checks.**
Ingest rejects a translation that is empty,
loses or adds a `{placeholder}` or markup,
is far shorter or longer than its source,
is in the wrong script,
or is an unmarked copy of its source.

**Use.**
`build` uses the curated translations of the current English texts
(`data/curated/translations/<lang>.json`).
A UI string not translated (or whose English text has changed since)
is shown in English, an occupation in Slovak,
and `build` logs the counts per language.
`check` fails while any UI string is untranslated
and reports the share of occupations translated per language.

## `obvod-rules`

One municipality per job,
the most addresses first (priority `addresses`).
An agent finds the resolution that sets a municipality's council obvody
on its official website and transcribes it into rules
by street, house numbers (ranges, odd/even, súpisné or orientačné),
part of the municipality or cadastral area
(format and matching: `src/election_map_slovakia/obvody.py`),
or reports it not found with the URLs tried.

```sh
uv run ems addresses                          # data/build/<day>/obvod-addresses/
uv run ems job make obvod-rules               # every municipality still to do
uv run ems job make obvod-rules --only Pezinok 545651   # by name or code
uv run ems job make obvod-rules --election 2026         # by slug or day
uv run ems job ingest data/jobs/obvod-rules-*
uv run ems make                               # addresses, geo, build, check
```

**Checks.**
Ingest accepts a rule set only if:

- its documents are on the municipality's own website
  (a domain carrying its name,
  or the state's central notice board `cuet.slovensko.sk`),
  directly or as an Internet Archive snapshot of such a page
  (`https://web.archive.org/web/<timestamp>/<original URL>`,
  fetched as archived, of the day the URL names),
  or linked from such a page among the documents
  (a file store such as Google Drive, a CMS host
  that does not name the municipality),
  and can be fetched;
- its `date`, where given, is before the election day
  (older than two years only gets a note:
  a council may keep the obvody of an earlier term);
- every street, part and cadastral area it names
  exists in the address register;
- it has the candidate lists' obvody,
  with the seats the Statistical Office's results give
  where the candidate data has them (2022);
  and beside them only an obvod the decision sets
  that no candidate stood in:
  marked `uncontested`, with the document (one of its documents)
  that lists it, the decision's `council_seats` then given
  and the obvody's seats adding up to them
  (an obvod the lists lack without that is refused);
- every address of the municipality lands in exactly one obvod.

For a by-election (`--election 2019-04`),
the municipalities are those of its council contests
whose council its term (the regular election before it)
elected in several obvody:
the council whose seats it fills was elected in the term's obvody,
so the item lists the obvody of both candidate lists
(and of the term's contests held nowhere, uncontested)
with the term's seats,
and the prompt asks for the term's decision;
the rules must have at least those obvody,
and none is a by-election's own uncontested one
(the term's job records it).

Ingest also notes, without rejecting,
an obvod whose share of the addresses is more than three times
its share of the voters on the roll (of its okrsky in the results),
or less than a third:
the review sheet and the ingest report list such notes
(`review/<obec>.notes.json`).

Each checked item gets a review sheet,
`data/jobs/obvod-rules-NNN/review/<obec>.html`:
the obvody as the map will draw them,
every address point coloured by obvod,
the rules and the document's text.

**Output,** in the data of the job's election,
`data/curated/elections/<election day>/`:

- accepted rule sets go to `obvody/oz/`,
  their documents to `data/curated/cache/<sha256>.<ext>`,
  their uncontested obvody to `uncontested.toml`
  (in place of what it had of the municipality;
  `candidates` makes them contests without candidates,
  [pipeline.md](pipeline.md#candidates));
- municipalities reported not found go to `obvody/oz-not-found.json`
  (made again only when named with `--only`).

**Estimates.**
Where a municipality publishes only the obvody's names and seats,
a hand-made rule set marked `estimated = true`
places the addresses by guess
(parts, or the nearest of `near` points
such as hamlets or the ends of the village,
explained in its `note`);
the ballots say the obvody are an estimate.

## `okrsok-rules`

One municipality per job,
the most addresses first (priority `addresses`).
Transcribes the okrsky (polling districts)
of every municipality with several:
the agent finds the decision that set them on the municipality's website.

- **A municipality with a rule set of council obvody**
  (whose documents, often listing the okrsky too,
  the job hands over with local copies):
  the agent writes which okrsky make up each obvod
  and, for the obvody with several,
  rules that share the obvod's addresses among its okrsky;
  or, where no document lists the okrsky's streets,
  only which okrsky make up each obvod.
- **A municipality without** (one that elects its council in one obvod,
  or any municipality in a vote that elects no council:
  [Another vote](#another-vote)):
  rules that share all its addresses among the okrsky
  (often by part of the municipality).

The rules take the form of the obvod rules.
Each item names the vote (`vote`: the election and its day,
a presidential election's round 2 too)
and has the municipality's code, name, okres and kraj,
its okrsky (`okrsky`) and, where the results have them,
each okrsok's voters on the roll (`voters`).

```sh
uv run ems fetch --only units-oso2026         # okrsky per municipality, ŠÚ SR (2026's units)
uv run ems addresses                          # data/build/<day>/obvod-addresses/
uv run ems job make okrsok-rules              # every municipality still to do
uv run ems job ingest data/jobs/okrsok-rules-*
uv run ems make                               # geo draws them, build uses them
```

**Checks.**
Ingest accepts the okrsky only if:

- their documents are official and dated as for `obvod-rules`;
- they are numbered 1..N
  for the N okrsky the Statistical Office lists for the municipality,
  each in one obvod,
  and each obvod has the okrsky the results count in it, where known;
- every address of an obvod with several okrsky
  (of the municipality, without obvody)
  lands in exactly one of them,
  and each such okrsok has addresses;
- no okrsok rule selects only addresses of another obvod;
- the okrsky can be drawn within their obvod.

Okrsky whose share of the addresses is far off their share of the voters
are noted, as for the obvody.

The review sheet, `data/jobs/okrsok-rules-NNN/review/<obec>.html`,
draws the okrsky within the obvody.

**Output,** in the data of the job's election:

- accepted okrsky are added to the rule set,
  or, for an item without obvody,
  written to `okrsky/<obec>.toml`
  (removing a rule set `ems job reuse` copied only to place copied okrsky);
- municipalities reported not found go to `okrsky/not-found.json`,
  losing any okrsky an earlier ingest gave them,
  but not okrsky copied from another election
  (`okrsky_reused`, `okrsky_adopted`), which record no search
  (made again only when named with `--only`).

**Use.**
With the okrsky known, `ems geo` draws them,
and the ballots give a council obvod the 2022 turnout of its okrsky,
where the municipality has the same okrsky as then
(`build.council_past`).

## An earlier election

`obvod-rules` and `okrsok-rules` work for an election other than the
latest too (`--election 2022`).
The municipalities' websites may show a later election's obvody and
okrsky by now, so the prompts add a section on that election:

- only documents valid for it count
  (for 2022: the council's decision on the obvody and seats of mid-2022,
  the okrsky set for the 2022 elections),
  live or in the Internet Archive,
  never a later election's;
- the items carry what the Statistical Office counted:
  each obvod's `seats` and `okrsky`, and each okrsok's `voters`;
- the okrsky of a referendum within a year of the election
  ([A referendum's okrsky](#a-referendums-okrsky)) may stand in.

Ingest then also requires:

- every document dated before the election day
  (for a referendum's okrsky, before the later of the two votes):
  by `date`, the decision's date as a document states it,
  or, where no document states it, approximately (below);
- the okrsky of each obvod those of the Statistical Office's results
  (2022: `tab02bf`), and their numbers those of its territorial division;

and notes okrsky whose share of their obvod's addresses
is far off their share of its voters,
as for the obvody.

**Approximate dating.**
An undated document may still be the best source,
so the output may date it approximately instead of by `date`:
`date_approximate` says how, `date_basis` says it in words,
and the ingest checks that it ties the document to the election:

- `archived`: the Internet Archive captured the document,
  or the official page linking it, before the vote;
  `date_source` is that snapshot, `date_seen` its day;
- `posted`: the official page (live or archived), `date_source`,
  says it was posted ("vyvesené", "zverejnené") on `date_seen`,
  before the vote;
- `named`: the document names the election.

A capture or posting only after the vote is rejected:
it may be of a later vote's document (2023's referendum, 2026's),
so only a document naming the election may rest on later evidence.
The checks on the content still apply
(the Statistical Office's okrsky, seats and grouping),
which also bear out that the document is the election's,
and a capture or posting more than two years before the vote gets a note.
The rule set records it as `date_approximate`, `date_seen` and
`date_basis` (`okrsky_date_*` for the okrsky;
`src/election_map_slovakia/obvody.py`),
and the ballots and the map say that the document's date is uncertain
and what dates it: it may be older than the election.
A municipality reported not found whose note holds a transcription
and such evidence is made again with `--only` and ingested;
`--only` also brings back one whose council rule set is reused,
which its own document then replaces.

**Supplements from a later source.**
Where the earlier election's document does not place every address
(houses or hamlets it leaves out, hamlets the register keeps
under another part, a split it leaves unclear or plainly gets wrong:
addresses far off the voters on the roll),
a later source may fill it in rather than a guess
(`fill_nearest`, inferred rules):
the output marks each rule taken from it `"supplemented": true`
and names the source in `supplement`
(`from`: `election`, the later election's rule set in the repository,
each marked rule being one of its rules;
`document`, a later document of the municipality, listed among the
documents and so on its website;
for okrsky also `referendum`, the referendum's document;
`day`, that vote's day or the document's date;
`basis`, what was taken for which addresses).
The ingest accepts it only for an earlier election,
from a source after it,
beside rules of the election's own document (never all rules),
and the checks on the content still apply.
The rule set records it as `supplemented`, `supplemented_from`,
`supplement_basis` (`okrsky_supplemented`, … for the okrsky;
`src/election_map_slovakia/obvody.py`),
and the ballots and the map say that part of the borders
comes from that source, so the election's state may have differed.
A transcribed rule set is redone by removing its file
(`obvody/oz/<obec>.toml`; its okrsky then need their job again)
and making the job with `--only`;
okrsky are made again with `--only` alone.

**Reuse.**
Where no document of the earlier election is found
(the not-found lists),
`ems job reuse --election 2022` copies the latest election's rules,
but only where the layout provably stayed the same
(`src/election_map_slovakia/reuse.py`):

- council obvody: the same obvod numbers with the same seats,
  the same okrsky in each obvod
  (the earlier results against the latest rule set's okrsky),
  each okrsok's voters on the roll within 10 % of the earlier count
  (the earlier election's results against the latest's);
  the okrsky come along;
- okrsky alone (a municipality with one obvod in both elections,
  or whose earlier obvody were transcribed):
  the same okrsky per obvod, the voters within 10 %;
- and the copy must pass the jobs' checks on the earlier addresses:
  every address in one obvod and okrsok, each with addresses,
  the okrsky drawable.

The copy is marked `reused` (the council rule set)
or `okrsky_reused` with the latest election's day and a note;
the municipality stays in the not-found list, which records the search.

**Stand-ins.**
Reuse claims that the layout is the same;
a supplement fills in what the election's own document leaves out.
A stand-in claims neither:
where units stay unknown after the reuse
(no document of the election found, or none that places the addresses:
it names the obvody but not their houses, or gives the okrsky only by obvod),
the same `ems job reuse`, for any election (the latest too),
draws them with another vote's rather than leave them unknown.
For each municipality and kind of unit
it takes the vote nearest in time, before or after
(of two as near the later),
whose units of the municipality are its own:
transcribed for it, not reused nor a stand-in themselves (no chains,
but for a by-election's council obvody, below);
where that one does not fit, the next nearest:

- council obvody, where the election elects the council in several:
  a regular election's rule set with the same obvod numbers and seats;
  a by-election's only from the regular election of its term,
  the obvody that voted among them
  (a later council's obvody are another council's),
  even where that rule set is another vote's itself
  (reused, or a stand-in there):
  the council whose seats the by-election fills was elected in them,
  however the term draws them,
  and the copy names the vote whose borders they are;
  a lone obvod 1 with its seats counts too,
  where the term elected the council in several obvody
  (Divina, 2026-03-21: obvod 1 of 3);
  the okrsky come along where they fit as below,
  else each obvod gets the okrsky the Statistical Office counted in it
  without rules (drawn where it has one, the okrsok then being the obvod);
- okrsky, of a municipality that voted in several:
  as many as the election's territorial division counts,
  per council obvod where the election elects them
  (into the council rule set, from one with the same obvod numbers);
  any vote's own okrsky may stand in
  (the 2024 EP election's for the 2024 presidential one,
  before the 2022 municipal elections');
- where the voters on the roll of each unit are known for both votes,
  within 25 % (farther apart, the layout clearly changed);
  where they are not known, the units stand in all the same;
- and the copy must pass the jobs' checks on the election's addresses.

Okrsky numbered otherwise
(Bratislava-Nové Mesto had 45 in 2022 and 32 in 2026)
are not mapped onto each other.
The copy is marked `adopted` with `adopted_basis`
(the council rule set; `okrsky_adopted` and `okrsky_adopted_basis`
for its okrsky where they are drawn)
or `okrsky_adopted` with `okrsky_adopted_basis`,
with the source vote's day;
the basis says why the election has none of its own
(the note of its not-found list, where the municipality is in it),
which vote stands in and why that one (the nearer ones not taken, and why),
and the voters of both votes where known.
A stand-in is never reused or supplemented,
and is chosen anew on each run (a proven copy replaces it;
one that no source fits any more is withdrawn).
The report gives each municipality's outcome,
then per election the stand-ins by source
and the units left unknown by reason:
no other vote has such units of its own,
none fits structurally, the voters differ too much,
or no fitting source fits the addresses.
`--only` on the obvod-rules job brings a municipality with a stand-in back,
whose own document then replaces the rule set;
the okrsok-rules job takes up stand-in okrsky as it does copied ones.

The flags reach the app in `data/index.json`
(`reused`, `adopted`, `okrsky_reused`, `okrsky_adopted`,
`okrsky_referendum`, `date_approximate`, `okrsky_date_approximate`,
`supplemented`, `okrsky_supplemented`),
so that it can say the borders are another vote's
(for stand-ins, that they are only indicative),
from a document whose date is uncertain,
or partly from a later source.

```sh
uv run ems addresses --election 2022
uv run ems job make obvod-rules --election 2022
uv run ems job ingest data/jobs/obvod-rules-*
uv run ems addresses --election 2022          # the okrsok jobs need the obvody
uv run ems job make okrsok-rules --election 2022
uv run ems job ingest data/jobs/okrsok-rules-*
uv run ems job reuse --election 2022
uv run ems make
```

## A referendum's okrsky

The mayor sets the okrsky anew for every vote,
mostly as they were.
The okrsky document of a referendum
held within a year of a vote, before or after it,
may stand in for the vote's own
(`okrsokrules.referenda`: the referendums in `config/elections.toml`
within `STAND_IN`, a year, of the vote's day, but the vote itself;
21 January 2023 for the elections of 2022 and the by-elections of 2023,
4 July 2026 for those of 2026, 2025-09 and 2026-03):

- where its document says the okrsky are those of the vote
  (a referendum after it),
  or the vote's document says they are those of the referendum
  (a referendum before it, both documents listed),
  or where no document of the vote is found;
- the output sets `referendum` (its day) and says which in `note`,
  and the okrsky are marked `okrsky_referendum`,
  which the map says;
- every document dated before the later of the two votes,
  and the okrsky still those the Statistical Office counts.

A referendum's document may also fill in the vote's own
(a supplement `"from": "referendum"`), from a referendum after the vote.
The documents of other votes count only so,
as supplements from a later election's rule set or document,
or through `ems job reuse` (below), which proves its copies:
no other vote's document can be marked as such on the map.

## Another vote

A country-wide election (presidential, a referendum)
or a by-election
has its okrsky transcribed by `okrsok-rules` too
(`--election 2024-prezident`, `--election 2023-03`),
from the municipalities' documents for that vote
("určenie volebných okrskov a volebných miestností"),
live or in the Internet Archive.
The prompt names the vote
(a presidential election's round 1 and round 2 days,
the referendum, the by-elections and their day)
and adds a section on such a vote
instead of the one on an earlier election:
its documents only, dated as above,
with supplements and a referendum's okrsky as above.

- **Items:** every municipality voting in several okrsky
  (the election's `units`;
  of a by-election only those with a mayor or council contest:
  ŠÚ SR's territorial division lists those where it was called off too)
  without okrsky of its own:
  none, or only a copy (`okrsky_reused`, `okrsky_adopted`),
  which the job then shows (`copied`: its election's day and documents,
  with local copies, for orientation).
  A copy stays until the vote's own document is accepted;
  a municipality reported not found keeps it.
- **Without obvody:** the okrsky are written for the whole municipality,
  to `okrsky/<obec>.toml`, as for a municipality with one council obvod.
  Only a by-election's municipality with a council contest
  whose council rule set is in the by-election's data
  (copied by `ems job reuse`, below, or by hand)
  gets its okrsky by obvod, added to that rule set.
- **Checks:** as many okrsky as the territorial division counts,
  numbered 1..N;
  the voters on the roll per okrsok from the election's results
  (`okrsokrules.okrsok_voters`: a country-wide election's first contest,
  a by-election's contests;
  those of a council by-election in some obvody only for their okrsky,
  none for the by-elections of 2018–2022, whose packages have no results
  per okrsok) for the notes on okrsky far off their voters;
  a by-election's okrsky by obvod against the obvody that voted only.

An agent can take one municipality's jobs of every vote at once:
make each vote's jobs for its code and hand the agent those directories
(each job's `input.json` names its election, each item its vote).

```sh
obec=…                                        # the municipality's code
for e in 2019-prezident 2023-referendum 2024-prezident 2026-referendum 2023-03; do
  uv run ems addresses --election "$e"        # once per election
  uv run ems job make okrsok-rules --election "$e" --only "$obec"
done
uv run ems job ingest data/jobs/okrsok-rules-*
uv run ems make
```

## A country-wide election or a by-election

Before (or besides) the jobs,
`ems job reuse --election 2024-prezident` (or `2023-referendum`,
`2023-03`, …), run after the election's results are built,
copies okrsky from the regular elections, nearest in time first
(a by-election's only from those before it:
it fills seats of the council elected then, in that council's obvody),
for each municipality that voted in several (the election's `units`;
a by-election's with a contest)
and has neither okrsky nor a rule set yet (or only a stand-in):

- the okrsky of a municipality with one council obvod there
  (`okrsky/<obec>.toml`) as they are;
- a council rule set with its obvody (`obvody/oz/<obec>.toml`),
  which, where the vote elects no council, only place the okrsky:
  `ems geo` draws them within the whole municipality;
  in a by-election with a council contest they draw its obvody too;
- only where the source's okrsky are its own or reused (never a stand-in),
  place every address, are numbered 1..N for the N okrsky of the
  election, give each council obvod that voted (a by-election's)
  the okrsky that voted in it,
  each okrsok that voted with voters on the roll
  (`okrsokrules.okrsok_voters`)
  within 10 % of its count in the source,
  and fit the election's addresses.
  Without voters per okrsok
  (before the results, the by-elections of 2018–2022)
  nothing is proven and nothing copied.

The copy is marked `okrsky_reused` (the rule set also `reused`)
with the source election's day and a note saying so,
and whether a document of the election was searched for and not found;
rules a later source supplemented in the source lose that mark,
the header keeping the source file's.
Okrsky the source transcribed from the document of the vote itself
(the 2022 elections' marked `okrsky_referendum = 2023-01-21`)
are that referendum's own:
copied without `okrsky_reused`, with their documents, date and dating,
once their numbers are those of its territorial division,
and noted as the referendum's own.
Where a by-election's okrsky are not proven,
the council rule set of the regular election
still draws the council obvody that voted,
each with voters on the roll within 10 % of its count in the source:
it is copied without its okrsky, marked `reused`.
The report lists every municipality with the reason each source was refused.
Those still without okrsky (or council obvody) then get a stand-in
as any election does ([stand-ins](#an-earlier-election)):
the nearest vote's own, unproven, marked `okrsky_adopted` (`adopted`),
else they stay drawn whole.

```sh
uv run ems make --election 2024-prezident     # its results first
uv run ems job reuse --election 2024-prezident
uv run ems make
```

## `research`

An agent searches the allowlisted sites (`config/sources.toml`)
for what they say about each candidate.

**Selection.**
Jobs are of one election's candidates
(`--election`, by default the latest's),
per research language
(the `[research]` table:
Slovak agents search Slovak media and official sites,
Hungarian ones the Hungarian-language media, …)
and per constituency.
`--only` takes research languages and places,
a place selecting every candidate a resident can vote for,
from mayor and council up to regional president;
a country-wide election's candidates stand everywhere,
so only its contest ids select among them (`prezident:SK/2`).

- `person:<id>` selects one person, and a list of them keeps its order.
- `again` makes jobs for persons researched already,
  under new rules (their findings are replaced on ingest);
  only pending jobs then keep a person out.
- The one priority, `office` (the default),
  puts country-wide candidates first, then regional presidents,
  then mayors of the largest municipalities
  (by council candidates, a proxy of size),
  regional councillors and the rest.

An election other than the latest is researched
as its voters could know the candidates:
the prompt asks for pages published before its last round's day
(a presidential election's second round, whose voters had the campaign
between the rounds), and the checks refuse a finding without a date
or of a later one.

```sh
uv run ems job make research --only sk okres:807 --size 45   # Slovak, okres Michalovce
uv run ems job make research --only hu cs pl de uk okres:807 --size 150
uv run ems job make research --only sk oz:522279/2           # one constituency
uv run ems job make research --only sk again predseda:8      # once more, under new rules
uv run ems job make research --only sk person:9a9a5bf4bc1d person:f0a615feabae
uv run ems research status --only okres:807                  # coverage per language
uv run ems job make research --election 2024-prezident --only sk --size 1   # one job per candidate
uv run ems research read data/jobs/research-001 URL --person ID
echo '{"id": …}' | uv run ems research submit data/jobs/research-001
uv run ems job ingest data/jobs/research-*
```

| Helper | What it does |
|---|---|
| `ems research status` | counts the candidates of an election (`--election`, by default the latest) that `--only` selects: researched with the current allowlist, with findings, in pending jobs, still to do |
| `ems research read JOB URL` | prints as JSON whether the page may be cited for the job, its title, date, language and the passages naming the person (`--person`); caches the copy in the job |
| `ems research submit JOB` | checks output items from stdin as ingest does and puts those that pass into the job's `output.json` |

**A finding** is:

- a verbatim quote from an allowlisted page;
- a one-sentence claim in English and Slovak;
- its category:
  - `cv`: career (for a prominent person, the main roles only);
  - `affair`: a serious, established controversy:
    charges, a court decision against the candidate,
    another very serious matter an authority established;
  - `dispute`: a suspicion of wrongdoing that is not established:
    allegations of corruption, abuse of office and the like
    that are denied or unconfirmed, a complaint with no charges,
    a case ended in the candidate's favour,
    statements documented as false or as disinformation, smears;
- what ties the page to the candidate.

Only what makes a candidate stand out counts:
no election results, candidacies or the office held now,
which the site shows from the official data.
Both kinds of controversy are about the candidate's own conduct:
criticising someone or taking a political position is not one,
nor is what a relative, a colleague or their party did
unless the source ties the candidate's own act to it.
The prompt asks agents to search for controversies by name too,
and for a prominent person (a presidential candidate, a party leader,
the first names on a list, a minister, a member of parliament)
to list the affairs they know of and look for each one,
naming in `note` those no allowlisted page supports.

**Checks.**
Ingest (and `research submit`, which an agent can call per person
while it works) fetches every cited page
and keeps a sanitized copy
(`src/election_map_slovakia/cache.py`:
no scripts, frames or remote loads; images inlined;
from the Internet Archive's latest snapshot
where a site turns automated clients away).
It rejects a finding whose page
is not allowed for the job's categories, cannot be fetched,
does not contain the quote verbatim or does not name the person,
and, for an election other than the latest,
one whose page was not published before its last round's day
(the finding's `published`, else the page's date).
A person with no finding is recorded as researched, nothing found.

**Output.**
Accepted research goes to `data/curated/research/<id[:2]>/<id>.json`
(the election researched; per category: date, job; findings),
the copies to `data/curated/cache/<sha256>.html`.
The site shows them on the candidate card
with links to the original and to the copy (`/cache/`).
