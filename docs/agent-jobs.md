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
| `--election DAY` | the election whose work to make (ISO day or slug; default: the latest), for the kinds that work per election |
| `--only NAME …` | restrict to these; their meaning is the kind's |
| `--size N` | items per job (default: the kind's) |
| `--priority ORDER` | order of the items, if the kind has several |
| `--limit N` | write at most N jobs, the first ones |

`obvod-rules` and `okrsok-rules` work per election:
they read that election's candidate lists and build output
(`data/build/<election day>/`)
and write into its curated data.
Their jobs record it in `input.json` as `election`, its day,
and ingest uses that election, not the latest;
a job made before jobs recorded their election cannot be ingested
and must be made again.
A job not ingested yet keeps its items out of its own election's jobs only.
`research` is of the latest election only
(`--election` is refused):
an earlier election gets the findings of its candidates
linked to researched ones, published before its day,
and is never researched anew.
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
- every address of the municipality lands in exactly one obvod.

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
  their documents to `data/curated/cache/<sha256>.<ext>`;
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
- **A municipality that elects its council in one obvod:**
  rules that share all its addresses among the okrsky
  (often by part of the municipality).

The rules take the form of the obvod rules.

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
  (of the municipality, with one obvod)
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
  or, for a municipality with one obvod,
  written to `okrsky/<obec>.toml`;
- municipalities reported not found go to `okrsky/not-found.json`,
  losing any okrsky an earlier ingest gave them
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
- the okrsky of the referendum held within a year after the election
  (`okrsokrules.REFERENDA`: 21 January 2023 for 2022)
  may stand in where its document says they are unchanged,
  or where no document of the election is found:
  the output sets `referendum` (its day) and says which in `note`,
  and the okrsky are marked `okrsky_referendum`.

Ingest then also requires:

- every document dated before the election day
  (for a referendum's okrsky, before the referendum):
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

**Adoption.**
Reuse claims that the layout is the same;
a supplement fills in what the election's own document leaves out.
Adoption claims neither:
where no usable document of the earlier election places the addresses
at all (it names the obvody but not their houses,
or gives the okrsky only by obvod),
the owner may choose to draw the units with the latest election's rules
rather than leave them unknown.
Only the municipalities listed in the election's `adopt.toml`
(`data/curated/elections/2022-10-29/adopt.toml`: `obec`, `name`,
`units` = `obvody` or `okrsky`, and `basis`:
why there are no rules of its own and what is known to differ)
are adopted, by the same `ems job reuse`, never others.
The latest rules are taken as they stand,
and only where the earlier results land on the units drawn:

- obvody, for a municipality without a rule set of its own:
  the same obvod numbers and seats, each obvod's voters on the roll
  within 25 % of the earlier count;
  the okrsky come along where the latest rule set gives each obvod
  the okrsky the Statistical Office counted in it then,
  else each obvod gets the earlier okrsky without rules
  (drawn where it has one, the okrsok then being the obvod);
- okrsky, for a municipality whose earlier okrsky are known only by obvod:
  latest okrsky that place every address,
  the same okrsky in each obvod as the Statistical Office counted then,
  each okrsok's voters within 25 %;
- and the copy must pass the same checks on the earlier addresses.

Okrsky numbered otherwise
(Bratislava-Nové Mesto had 45 in 2022 and 32 in 2026)
are refused, not mapped onto each other.
The report says what was adopted and why anything was refused.
The copy is marked `adopted` with `adopted_basis`
(the council rule set; `okrsky_adopted` and `okrsky_adopted_basis`
for its okrsky where they are drawn)
or `okrsky_adopted` with `okrsky_adopted_basis`,
the basis followed by the voters of both elections;
an adopted rule set is never reused or supplemented.
`--only` on the obvod-rules job brings an adopted municipality back,
whose own document then replaces the rule set.

The flags reach the app in `data/index.json`
(`reused`, `adopted`, `okrsky_reused`, `okrsky_adopted`,
`okrsky_referendum`, `date_approximate`, `okrsky_date_approximate`,
`supplemented`, `okrsky_supplemented`),
so that it can say the borders are another vote's
(for adopted ones, that they are only indicative),
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

## `research`

An agent searches the allowlisted sites (`config/sources.toml`)
for what they say about each candidate.

**Selection.**
Jobs are of the latest election's candidates,
per research language
(the `[research]` table:
Slovak agents search Slovak media and official sites,
Hungarian ones the Hungarian-language media, …)
and per constituency.
`--only` takes research languages and places,
a place selecting every candidate a resident can vote for,
from mayor and council up to regional president.

- `person:<id>` selects one person, and a list of them keeps its order.
- `again` makes jobs for persons researched already,
  under new rules (their findings are replaced on ingest);
  only pending jobs then keep a person out.
- The one priority, `office` (the default),
  puts regional presidents first,
  then mayors of the largest municipalities
  (by council candidates, a proxy of size),
  regional councillors and the rest.

```sh
uv run ems job make research --only sk okres:807 --size 45   # Slovak, okres Michalovce
uv run ems job make research --only hu cs pl de uk okres:807 --size 150
uv run ems job make research --only sk oz:522279/2           # one constituency
uv run ems job make research --only sk again predseda:8      # once more, under new rules
uv run ems job make research --only sk person:9a9a5bf4bc1d person:f0a615feabae
uv run ems research status --only okres:807                  # coverage per language
uv run ems research read data/jobs/research-001 URL --person ID
echo '{"id": …}' | uv run ems research submit data/jobs/research-001
uv run ems job ingest data/jobs/research-*
```

| Helper | What it does |
|---|---|
| `ems research status` | counts the latest election's candidates that `--only` selects: researched with the current allowlist, with findings, in pending jobs, still to do |
| `ems research read JOB URL` | prints as JSON whether the page may be cited for the job, its title, date, language and the passages naming the person (`--person`); caches the copy in the job |
| `ems research submit JOB` | checks output items from stdin as ingest does and puts those that pass into the job's `output.json` |

**A finding** is:

- a verbatim quote from an allowlisted page;
- a one-sentence claim in English and Slovak;
- its category:
  - `cv`: career;
  - `affair`: a serious, established controversy:
    charges, a court decision against the candidate,
    another very serious matter an authority established;
  - `dispute`: a disputed or lesser one:
    allegations denied or unconfirmed, a complaint with no charges,
    a case ended in the candidate's favour, a political quarrel;
- what ties the page to the candidate.

Only what makes a candidate stand out counts:
no election results, candidacies or the office held now,
which the site shows from the official data.

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
does not contain the quote verbatim or does not name the person.
A person with no finding is recorded as researched, nothing found.

**Output.**
Accepted research goes to `data/curated/research/<id[:2]>/<id>.json`
(per category: date, job; findings),
the copies to `data/curated/cache/<sha256>.html`.
The site shows them on the candidate card
with links to the original and to the copy (`/cache/`).
