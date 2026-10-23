# Agent jobs

Work that needs judgement (translating, reading municipal resolutions,
researching candidates) is done by AI agents through job directories:

```sh
uv run ems job make translation                 # every job still to do
uv run ems job make translation --only cs ui    # restrict (languages, parts)
uv run ems job make translation --size 500      # items per job
uv run ems job ingest data/jobs/translation-001 # check and merge output.json
```

`make` writes `data/jobs/<kind>-NNN/` with `input.json` (the items),
`schema.json` (the JSON Schema of the expected `output.json`), `prompt.md`
(the instructions) and `README.md` (how to run it); an agent with only that
directory (and the web, where the prompt needs it) writes `output.json`.
`ingest` validates it against the schema and the kind's deterministic checks,
merges the accepted items into `data/curated/` and lists the rejected ones
with their reasons in `ingest-report.md`; ingesting again is harmless.
Items already curated, or in a job not ingested yet, are not made again;
`ingest` skips a job without `output.json`, which stays pending, so
`ems job ingest data/jobs/translation-*` can run while agents still work.
Items rejected at ingest go into new jobs the next time `make` runs.
`data/jobs/` is git-ignored scratch; what is committed is `data/curated/`.
The framework is `src/election_map_slovakia/jobs.py`, the translation kind
`translate.py`, the obvod-rules kind `obvodrules.py`, the research kind
`research.py`.

`translation` jobs translate the UI strings (from English, with the Slovak
for reference, one job per language), the candidates' occupations (from
Slovak, most frequent first, about 900 per job) into every enabled language
but Slovak, and the research claims (from English) and quotes (from the
page's language) into the other languages. The checks reject a translation
that is empty, loses or adds a `{placeholder}` or markup, is far shorter or
longer than its source, is in the wrong script, or is an unmarked copy of
its source. `build` uses the
curated translations of the current English texts; a UI string not
translated (or whose English text has changed since) is shown in English,
an occupation in Slovak, and `build` logs the counts per language. `check`
fails while any UI string is untranslated and reports the share of
occupations translated per language.

`obvod-rules` jobs (one municipality per job, the most addresses first)
have an agent find the resolution that sets a municipality's council obvody
on its official website and transcribe it into rules by street, house
numbers (ranges, odd/even, súpisné or orientačné), part of the municipality
or cadastral area (format and matching: `src/election_map_slovakia/obvody.py`),
or report it not found with the URLs tried:

```sh
uv run ems addresses                          # data/build/obvod-addresses/
uv run ems job make obvod-rules               # every municipality still to do
uv run ems job make obvod-rules --only Pezinok 545651   # by name or code
uv run ems job ingest data/jobs/obvod-rules-*
uv run ems make                               # addresses, geo, build, check
```

Ingest accepts a rule set only if its documents are on the municipality's
own website (a domain carrying its name, or the state's central notice
board `cuet.slovensko.sk`) and can be fetched, every street, part and
cadastral area it names exists in the address register, it has the
candidate lists' obvody, and every address of the municipality lands in
exactly one obvod. Each checked item gets a review sheet,
`data/jobs/obvod-rules-NNN/review/<obec>.html`: the obvody as the map will
draw them, every address point coloured by obvod, the rules and the
document's text. Accepted rule sets go to `data/curated/obvody/oz/`, their
documents to `data/curated/cache/<sha256>.<ext>`, municipalities reported
not found to `data/curated/obvody/oz-not-found.json` (made again only when
named with `--only`). Where a municipality publishes only the obvody's
names and seats, a hand-made rule set marked `estimated = true` places the
addresses by guess (parts, or the nearest of `near` points such as hamlets
or the ends of the village, explained in its `note`); the ballots say the
obvody are an estimate.

`research` jobs have an agent search the allowlisted sites
(`config/sources.toml`) for what they say about each candidate. They run
per research language (the `[research]` table: Slovak agents search Slovak
media and official sites, Hungarian ones the Hungarian-language media, …)
and per constituency: `--only` takes research languages and places, a
place selecting every candidate a resident can vote for, from mayor and
council up to regional president; `person:<id>` selects one person, and a
list of them keeps its order:

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

A finding is a verbatim quote from an allowlisted page, a one-sentence
claim in English and Slovak, whether it is career (`cv`), a serious,
established controversy (`affair`: charges, a court decision against the
candidate, another very serious matter an authority established) or a
disputed or lesser one (`dispute`: allegations denied or unconfirmed, a
complaint with no charges, a case ended in the candidate's favour, a
political quarrel), and what ties the page to the candidate. Only what
makes a candidate stand out counts: no election results, candidacies or
the office held now, which the site shows from the official data. Ingest
(and `research submit`, which an agent can call per person while it works)
fetches every cited page, keeps a sanitized copy
(`src/election_map_slovakia/cache.py`: no scripts, frames or remote loads;
images inlined; from the Internet Archive's latest snapshot where a site
turns automated clients away) and rejects a finding whose page is not
allowed for the job's categories, cannot be fetched, does not contain the
quote verbatim or does not name the person. A person with no finding is
recorded as researched, nothing found. Accepted research goes to
`data/curated/research/<id[:2]>/<id>.json` (per category: date, job;
findings), the copies to `data/curated/cache/<sha256>.html`; the site
shows them on the candidate card with links to the original and to the
copy (`/cache/`).
