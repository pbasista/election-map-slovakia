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
| `--only NAME …` | restrict to these; their meaning is the kind's |
| `--size N` | items per job (default: the kind's) |
| `--priority ORDER` | order of the items, if the kind has several |
| `--limit N` | write at most N jobs, the first ones |

### A job directory

`make` writes `data/jobs/<kind>-NNN/` with:

- `input.json`: the items;
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
- the candidates' occupations, from Slovak,
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
uv run ems addresses                          # data/build/obvod-addresses/
uv run ems job make obvod-rules               # every municipality still to do
uv run ems job make obvod-rules --only Pezinok 545651   # by name or code
uv run ems job ingest data/jobs/obvod-rules-*
uv run ems make                               # addresses, geo, build, check
```

**Checks.**
Ingest accepts a rule set only if:

- its documents are on the municipality's own website
  (a domain carrying its name,
  or the state's central notice board `cuet.slovensko.sk`)
  and can be fetched;
- every street, part and cadastral area it names
  exists in the address register;
- it has the candidate lists' obvody;
- every address of the municipality lands in exactly one obvod.

Each checked item gets a review sheet,
`data/jobs/obvod-rules-NNN/review/<obec>.html`:
the obvody as the map will draw them,
every address point coloured by obvod,
the rules and the document's text.

**Output,** in the election's data,
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
uv run ems fetch --only units-oso2026         # okrsky per municipality, ŠÚ SR
uv run ems addresses                          # data/build/obvod-addresses/
uv run ems job make okrsok-rules              # every municipality still to do
uv run ems job ingest data/jobs/okrsok-rules-*
uv run ems make                               # geo draws them, build uses them
```

**Checks.**
Ingest accepts the okrsky only if:

- their documents are official (as for `obvod-rules`;
  a file on a CMS host that does not name the municipality,
  such as `obec.dobraobec.sk/files/<n>/…`, also
  when an official page among the documents links to it);
- they are numbered 1..N
  for the N okrsky the Statistical Office lists for the municipality,
  each in one obvod;
- every address of an obvod with several okrsky
  (of the municipality, with one obvod)
  lands in exactly one of them,
  and each such okrsok has addresses;
- no okrsok rule selects only addresses of another obvod;
- the okrsky can be drawn within their obvod.

The review sheet, `data/jobs/okrsok-rules-NNN/review/<obec>.html`,
draws the okrsky within the obvody.

**Output,** in the election's data:

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

## `research`

An agent searches the allowlisted sites (`config/sources.toml`)
for what they say about each candidate.

**Selection.**
Jobs run per research language
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
| `ems research status` | counts the candidates `--only` selects: researched with the current allowlist, with findings, in pending jobs, still to do |
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
