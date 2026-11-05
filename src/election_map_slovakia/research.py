"""The ``research`` job kind: what allowlisted media and official sites say about candidates.

Each item of a job is one person (``candidates.json``): name, age,
occupation, residence, every candidacy and office held now, and the official
websites of the places they stand in. The agent searches the sites of the
job's categories (``config/sources.toml``: ``[research]`` maps a language to
the categories its agents search), decides which hits are about this person
and not a namesake, and reports each relevant fact as a finding: the page,
a verbatim quote, a one-sentence claim in English and Slovak, whether it is
career (``cv``), a serious, established controversy (``affair``) or a
disputed or lesser one (``dispute``), and what in the source ties it to
the candidate. A person with no finding is reported with an empty list:
"researched, nothing found" is a result too.

Research is of one election's candidates (its ``candidates.json``; ``ems
job make research --election``, by default the latest's): its findings are
kept by person in one store, each record naming the election researched.
An election not researched in its own right gets the findings of its
persons linked to the latest election's researched ones, published before
its last round's day (``reused_research`` of
:mod:`election_map_slovakia.bundle`). An election other than the latest is
researched as its voters could know the candidates: only pages published
before its last round's day count (:func:`cutoff`; the prompt says so, and
the check rejects a finding without such a date). It runs per
language and constituency: ``--only`` takes research
languages (``sk``, ``hu``, …; none: all) and places, which select every
candidate a resident of the place can vote for: ``okres:<code>``,
``kraj:<code>``, an obec code, or a contest id (``oz:522279/2``,
``zsk:8/7``, ``predseda:8``, ``prezident:SK/1``) for that contest alone;
a country-wide election's candidates stand everywhere, so only its
contests select among them. ``person:<id>`` selects one person; the
persons named so come after those the places select, in the order given.
A person already researched in all of a language's categories, or in a
pending job of that language, is left out, unless ``again`` is among
them: then only pending jobs keep a person out, so that research done
under older rules can be done again (its findings are replaced on ingest).
The one priority, ``office``, puts the country-wide candidates first, then
regional presidents, mayors of the largest municipalities (by council
candidates, a proxy of size), regional councillors and the rest.

``check`` (run by ``ems job ingest`` and ``ems research submit``) accepts an
item only if every finding

- cites a URL allowed under one of the job's categories (:mod:`sources`);
- can be fetched as a web page and cached (:mod:`cache`): the copy goes to
  the job's ``documents/``;
- quotes the page verbatim (:func:`cache.normalize`; an ellipsis may join
  parts that appear in that order);
- is on a page that names the person (first name and surname, allowing for
  Slovak inflection: :func:`name_stem`);
- for an election other than the latest, was published before its last
  round's day (:func:`cutoff`; the finding's ``published``, else the
  page's).

``accept`` records, per person, the election researched (its ISO day),
the date and job of each category researched, and replaces that category's
findings with the new ones, in
``data/curated/research/<id[:2]>/<id>.json``::

    {"name": "...", "election": "YYYY-MM-DD", "researched": {category: {date, job}},
     "findings": [{category, url, title, published, language, cache,
                   fetched, via, kind, claim: {en, sk}, quote, identity,
                   job}]}

and copies the cached pages to ``data/curated/cache/<sha256>.html``.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from election_map_slovakia import cache, candidates, contests as kinds, jobs, sources
from election_map_slovakia.config import OBEC_CODE, OKRES_CODE, Config, Election

NAME = "research"
CURATED_DIR = "research"
CACHE_DIR = "cache"
"""Below ``data/curated/``, shared with the documents of the obvod rule sets."""
DOCUMENTS_DIR = "documents"
PRIORITY = "office"
DEFAULT_SIZE = 40
KINDS = ("cv", "affair", "dispute")
MIN_QUOTE = 20
MAX_QUOTE = 600
MAX_CLAIM = 300
_PASSAGE = 400
_MAX_PASSAGES = 8
_MIN_STEM = 3
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\]|\[…\])\s*")
_CONTEST = re.compile(r"(starosta|oz|predseda|zsk):([0-9A-Z]+)(?:/(\d+))?")
_COUNTRY = re.compile(r"(prezident|nrsr|ep):SK(?:/(\d+))?")
_KRAJ = re.compile(r"kraj:(\d)")
AGAIN = "again"
"""The ``--only`` token that makes research of persons researched already."""
PERSON = "person:"
"""The prefix of an ``--only`` token that selects one person by id."""
_RANK = {
    "prezident": 0,
    "nrsr": 0,
    "ep": 0,
    "predseda": 1,
    "starosta": 2,
    "zsk": 3,
    "oz": 4,
}
LANGUAGE_NAMES = {
    "sk": "Slovak",
    "hu": "Hungarian",
    "cs": "Czech",
    "pl": "Polish",
    "de": "German",
    "uk": "Ukrainian",
    "en": "English",
}

_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["url", "kind", "claim_en", "claim_sk", "quote", "identity"],
    "additionalProperties": False,
    "properties": {
        "url": {"type": "string", "pattern": "^https?://"},
        "title": {"type": "string"},
        "published": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "kind": {"enum": list(KINDS)},
        "claim_en": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM},
        "claim_sk": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM},
        "quote": {"type": "string", "minLength": MIN_QUOTE, "maxLength": MAX_QUOTE},
        "identity": {"type": "string", "minLength": 1, "maxLength": MAX_CLAIM},
    },
}
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "queries", "findings"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "queries": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "findings": {"type": "array", "items": _FINDING_SCHEMA},
        "note": {"type": "string"},
    },
}


# --- selection --------------------------------------------------------------


def candidate_data(cfg: Config, election: Election) -> dict[str, Any]:
    """Return *election*'s ``candidates.json``; raise JobError if missing."""
    path = cfg.election_build_dir(election) / candidates.OUTPUT_FILE
    if not path.is_file():
        raise jobs.JobError(f"{path} missing; run `ems candidates` first")
    return json.loads(path.read_bytes())


def ballots(
    data: Mapping[str, Any], props: Mapping[str, Mapping[str, Any]]
) -> dict[str, set[str]]:
    """Return obec → the contests its residents vote in.

    Every council obvod of the obec counts: who lives where within it is the
    address's business.

    *props* is :func:`bundle.obec_props` (regional and city council obvod).
    """
    contests: dict[str, list[str]] = defaultdict(list)
    for c in data["contests"]:
        contests[str(c["area"])].append(c["id"])
    out = {}
    for o in data["obce"]:
        code = o["code"]
        if code in candidates.CITY_CODES:
            continue
        p = props.get(code, {})
        ids = {c for c in contests[code] if c.startswith(("starosta:", "oz:"))}
        ids |= {f"predseda:{o['kraj']}", f"zsk:{o['kraj']}/{p.get('zsk', 0)}"}
        if "city" in p:
            city = p["city"]
            ids |= {f"starosta:{city}", f"oz:{city}/{p['city_obvod']}"}
        out[code] = ids
    return out


def _contests_only(
    election: Election, known: set[str], places: Sequence[str]
) -> set[str]:
    """Return the contests *places* name, of country-wide *election*; fail on others.

    Its candidates stand everywhere: an obec, okres or kraj selects them all.
    """
    wrong = sorted(set(places) - known)
    if wrong:
        raise jobs.JobError(
            f"{NAME}: {wrong[0]!r} is no contest of the {election.slug} election,"
            " whose candidates stand everywhere"
        )
    return set(places)


def _places(
    cfg: Config,
    election: Election,
    data: Mapping[str, Any],
    places: Sequence[str],
) -> set[str]:
    """Return the contest ids *places* select (all contests for none).

    Places select a country-wide election's contests by id only: every
    candidate stands everywhere.
    """
    known = {c["id"] for c in data["contests"]}
    if not places:
        return known
    if election.kind in kinds.NATIONAL:
        return _contests_only(election, known, places)
    from election_map_slovakia import bundle, geo  # bundle imports this module

    props = bundle.obec_props(cfg.election_build_dir(election) / geo.OUTPUT_DIR)
    by_obec = ballots(data, props)
    selected: set[str] = set()
    for place in places:
        if place in known:
            selected.add(place)
            continue
        if place.startswith("okres:") and OKRES_CODE.fullmatch(place[6:]):
            obce = [o["code"] for o in data["obce"] if o.get("okres") == place[6:]]
        elif m := _KRAJ.fullmatch(place):
            obce = [o["code"] for o in data["obce"] if o["kraj"] == m.group(1)]
        elif OBEC_CODE.fullmatch(place) and place in by_obec:
            obce = [place]
        else:
            raise jobs.JobError(f"{NAME}: {place!r} is no contest, obec, okres or kraj")
        if not obce:
            raise jobs.JobError(f"{NAME}: {place!r} has no municipalities")
        for code in obce:
            selected |= by_obec.get(code, set()) & known
    return selected


def split_only(cfg: Config, only: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return (research languages, places) of ``--only``; see the module doc."""
    languages, places = [], []
    for token in only:
        if token == AGAIN:
            continue
        (languages if token in cfg.sources.research else places).append(token)
    return languages or list(cfg.sources.research), places


def selected_persons(
    cfg: Config, election: Election, data: Mapping[str, Any], places: Sequence[str]
) -> list[str]:
    """Return the persons *places* select: by priority, then the named ones.

    *data* is *election*'s ``candidates.json``.
    """
    named = [p.removeprefix(PERSON) for p in places if p.startswith(PERSON)]
    unknown = sorted(set(named) - {p["id"] for p in data["persons"]})
    if unknown:
        raise jobs.JobError(f"{NAME}: no person {', '.join(unknown)}")
    places = [p for p in places if not p.startswith(PERSON)]
    ranked = (
        _by_office(data, _places(cfg, election, data, places))
        if places or not named
        else []
    )
    seen = set(ranked)
    return ranked + [p for p in dict.fromkeys(named) if p not in seen]


def _by_office(data: Mapping[str, Any], contests: set[str]) -> list[str]:
    """Return the candidates in *contests*, in the order of :data:`PRIORITY`.

    A person ranks by their highest contest; municipal ones by the number of
    council candidates of the municipality, a proxy of its size.
    """
    size = Counter(
        _kind_area(c["contest"])[1]
        for c in data["candidacies"]
        if c["contest"].startswith("oz:")
    )
    rank: dict[str, tuple[int, int]] = {}
    for c in data["candidacies"]:
        if c["contest"] not in contests:
            continue
        kind, area = _kind_area(c["contest"])
        key = (_RANK[kind], -size[area] if kind in ("starosta", "oz") else 0)
        rank[c["person"]] = min(rank.get(c["person"], key), key)
    return sorted(rank, key=lambda p: (rank[p], p))


def _kind_area(contest: str) -> tuple[str, str]:
    """Return the kind and area of a contest id (``oz:522279/2`` → oz, 522279)."""
    kind, rest = contest.split(":", 1)
    return kind, rest.split("/", 1)[0]


def researched(cfg: Config, person: str, election: Election) -> dict[str, Any]:
    """Return the curated research of *person*, a candidate of *election* (empty if none)."""
    path = curated_path(cfg, person)
    if not path.is_file():
        return {}
    record = json.loads(path.read_bytes())
    return record if record["election"] == election.day.isoformat() else {}


def curated_path(cfg: Config, person: str) -> Path:
    """Return the curated research file of *person*."""
    return cfg.curated_dir / CURATED_DIR / person[:2] / f"{person}.json"


def done(record: Mapping[str, Any], categories: Iterable[str]) -> bool:
    """Return whether *record* covers *categories*."""
    seen = record.get("researched", {})
    return all(c in seen for c in categories)


# --- items --------------------------------------------------------------------


def contest_label(
    contest: str, names: Mapping[str, str], kraje: Mapping[str, str]
) -> str:
    """Return how a Slovak reader names *contest* (a contest id or a body)."""
    if m := _COUNTRY.fullmatch(contest):
        kind, sub = m.groups()
        if kind == "prezident":
            return "prezident Slovenskej republiky" + (f" ({sub}. kolo)" if sub else "")
        if kind == "nrsr":
            return "poslanec Národnej rady Slovenskej republiky"
        return "poslanec Európskeho parlamentu"
    m = _CONTEST.fullmatch(contest)
    if not m:
        return contest
    kind, area, obvod = m.groups()
    district = f", volebný obvod č. {obvod}" if obvod else ""
    # Kraj names are adjectives ("Košický"), which the nominative keeps.
    if kind == "predseda":
        return f"predseda samosprávneho kraja ({kraje[area]} kraj)"
    if kind == "zsk":
        return f"poslanec zastupiteľstva samosprávneho kraja ({kraje[area]} kraj){district}"
    place = names.get(area, area)
    if kind == "starosta":
        return f"starosta obce / primátor mesta {place}"
    return f"poslanec obecného / mestského zastupiteľstva {place}{district}"


def _full_name(c: Mapping[str, Any]) -> str:
    name = " ".join(x for x in (c["title_before"], c["first_name"], c["surname"]) if x)
    return f"{name}, {c['title_after']}" if c["title_after"] else name


def person_items(
    cfg: Config, data: Mapping[str, Any], persons: Sequence[str]
) -> list[dict[str, Any]]:
    """Return the job items of *persons*, in their order."""
    names = {o["code"]: o["name"] for o in data["obce"]}
    obce = {o["code"]: o for o in data["obce"]}
    kraje = {k["code"]: k["name"] for k in data["kraje"]}
    by_person: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in data["candidacies"]:
        by_person[c["person"]].append(c)
    residence = {p["id"]: p["obec"] for p in data["persons"]}
    municipal, regional = cfg.sources.municipal_sites, cfg.sources.regional_sites
    items = []
    for person in persons:
        cs = by_person[person]
        first = cs[0]
        places = {residence[person]} | {_kind_area(c["contest"])[1] for c in cs}
        kraj_codes = {obce[p]["kraj"] for p in places if p in obce} | {
            p for p in places if p in kraje
        }
        sites = sorted(
            {municipal[p] for p in places if p in municipal}
            | {regional[k] for k in kraj_codes if k in regional}
        )
        offices = [
            f"{contest_label(o['body'], names, kraje)} (od {o['since']})"
            for c in cs
            for o in c.get("incumbent", [])
        ]
        items.append(
            {
                "id": person,
                "name": _full_name(first),
                "first_name": first["first_name"],
                "surname": first["surname"],
                "age": first["age"],
                "occupation": first["occupation"],
                "residence": names.get(residence[person], residence[person]),
                "candidacies": [
                    {
                        "contest": contest_label(c["contest"], names, kraje),
                        "number": c["number"],
                        # A presidential candidate stands for no party,
                        # nor as an independent of a party-list contest.
                        "parties": c["parties"]
                        or (["nezávislý kandidát"] if c["independent"] else []),
                    }
                    for c in cs
                ],
                "in_office": sorted(set(offices)),
                "official_sites": sites,
            }
        )
    return items


def make(cfg: Config, options: jobs.MakeOptions) -> list[jobs.Batch]:
    """Return the research jobs still to do; see the module doc."""
    election = options.election
    languages, places = split_only(cfg, options.only)
    again = AGAIN in options.only
    data = candidate_data(cfg, election)
    persons = selected_persons(cfg, election, data, places)
    # A referendum has no candidates.
    if not persons:
        return []
    batches = []
    for lang in languages:
        categories = cfg.sources.research[lang]
        pending = {
            i["id"]
            for j in options.pending
            if j.context.get("language") == lang
            for i in j.items
        }
        todo = [
            p
            for p in persons
            if p not in pending
            and (again or not done(researched(cfg, p, election), categories))
        ]
        language = LANGUAGE_NAMES.get(lang, lang)
        context = {
            "language": lang,
            "categories": list(categories),
            "hosts": sources.hosts(cfg.sources, categories),
        }
        prompt = _prompt(cfg, election, language, categories)
        for start in range(0, len(todo), options.size):
            chunk = person_items(cfg, data, todo[start : start + options.size])
            title = (
                f"research in {language} sources:"
                f" {len(chunk)} candidates from {chunk[0]['name']}"
            )
            batches.append(jobs.Batch(chunk, prompt, title, context))
    return batches


_ELECTIONS = {
    "municipal-regional": "the Slovak municipal and regional elections",
    "municipal": "the Slovak municipal elections",
    "regional": "the Slovak regional elections",
    "by-election": "the Slovak municipal by-elections",
    "presidential": "the election of the President of the Slovak Republic",
    "parliament": "the election to the National Council of the Slovak Republic",
    "european": "the election to the European Parliament in Slovakia",
}
"""How the prompt names an election with candidates, by its label
(:attr:`config.Election.label`)."""


def cutoff(cfg: Config, election: Election) -> dt.date | None:
    """Return the day before which an election's findings must be published.

    That of an election other than the latest, researched as its voters
    could know the candidates: its last round's (a presidential election's
    second round, whose voters had the campaign between the rounds); None
    for the latest.
    """
    return None if election == cfg.latest else election.last_day


def _prompt(
    cfg: Config, election: Election, language: str, categories: Sequence[str]
) -> str:
    before = cutoff(cfg, election)
    return PROMPT.format(
        election=_ELECTIONS[election.label],
        day=jobs.long_date(election.day),
        language=language,
        categories=", ".join(categories),
        official=_OFFICIAL if sources.OFFICIAL in categories else "",
        past=_PAST.format(day=jobs.long_date(before)) if before else "",
        min_quote=MIN_QUOTE,
        max_quote=MAX_QUOTE,
        max_claim=MAX_CLAIM,
    )


# --- check --------------------------------------------------------------------


def name_stem(name: str) -> str:
    """Return the start of *name* every Slovak case form of it shares.

    Declension changes up to the last three letters ("Nováková" →
    "Novákovej", "Dufinec" → "Dufinca", "Jana" → "Janu"), so a name is cut
    by up to three letters, keeping at least three ("Ján" → "Jána" keeps it
    whole).
    """
    key = cache.normalize(name)
    return key[: max(_MIN_STEM, len(key) - 3)]


def names_person(text: str, first_name: str, surname: str) -> bool:
    """Return whether normalized *text* names the person.

    It must have words starting with the stems of the first name and surname,
    accents aside: lists and results tables often drop or vary them
    ("Tancoš" for "Táncoš"). The check only rules out pages that do not
    mention the person at all; whether a page is about the candidate or a
    namesake is the agent's call.
    """
    bare = _unaccented(text)
    return all(
        re.search(rf"(?<!\w){re.escape(_unaccented(name_stem(part)))}", bare)
        for name in (first_name, surname)
        for part in name.split()[:1]
    )


def _unaccented(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def quote_found(quote: str, text: str) -> bool:
    """Return whether *quote* is in normalized *text*.

    Parts an ellipsis joins must appear in that order.
    """
    position = 0
    for part in filter(None, (cache.normalize(p) for p in _ELLIPSIS.split(quote))):
        found = text.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def _documents(job: jobs.Job) -> dict[str, dict[str, str]]:
    path = job.path / DOCUMENTS_DIR / "index.json"
    return json.loads(path.read_bytes()) if path.is_file() else {}


def keep(cfg: Config, job: jobs.Job, url: str) -> tuple[dict[str, str], str]:
    """Return the record and text of *url*'s copy in the job.

    Archives the page first if needed; raises :class:`cache.CacheError`.
    """
    directory = job.path / DOCUMENTS_DIR
    with _locked(directory / "index.lock"):
        index = _documents(job)
        record = index.get(url)
        if record and (directory / f"{record['cache']}.txt").is_file():
            return record, (directory / f"{record['cache']}.txt").read_text("utf-8")
        page = cache.archive(cfg, url, dt.date.today())
        record = {
            "cache": page.sha256,
            "title": page.title,
            "language": page.language,
            "published": page.published,
            "fetched": page.fetched,
            "via": page.via,
        }
        (directory / f"{page.sha256}.html").write_bytes(page.html)
        (directory / f"{page.sha256}.txt").write_text(page.text, "utf-8")
        jobs.write_json(directory / "index.json", index | {url: record})
        return record, page.text


@contextlib.contextmanager
def _locked(path: Path) -> Generator[None]:
    """Hold an exclusive lock on *path*: an agent may run tools in parallel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def check(
    cfg: Config, job: jobs.Job, item: dict[str, Any], out: dict[str, Any]
) -> list[str]:
    """Return the problems of output item *out* for input *item*."""
    problems = []
    seen = set()
    for i, f in enumerate(out["findings"]):
        where = f"findings/{i}"
        key = (f["url"], cache.normalize(f["quote"]))
        if key in seen:
            problems.append(f"{where}: the same quote of the same page again")
            continue
        seen.add(key)
        problems += [f"{where}: {p}" for p in finding_problems(cfg, job, item, f)]
    return problems


def finding_problems(
    cfg: Config, job: jobs.Job, item: Mapping[str, Any], f: Mapping[str, Any]
) -> list[str]:
    """Return the problems of one finding *f* of the person *item*."""
    category = sources.category(f["url"], cfg.sources)
    if category is None:
        return [f"{f['url']} is not on the allowlist (or is excluded or blocked)"]
    if category not in job.context["categories"]:
        return [
            f"{f['url']} is in category {category}, which this job does not"
            f" search ({', '.join(job.context['categories'])})"
        ]
    if f.get("published") and (
        not _valid_date(f["published"])
        or dt.date.fromisoformat(f["published"]) > dt.date.today()
    ):
        return [f"published {f['published']!r} is no past date"]
    try:
        doc, text = keep(cfg, job, f["url"])
    except cache.CacheError as e:
        return [str(e)]
    normalized = cache.normalize(text)
    problems = []
    if not quote_found(f["quote"], normalized):
        problems.append("quote is not on the page verbatim")
    if not names_person(normalized, item["first_name"], item["surname"]):
        problems.append(
            f"the page does not name {item['first_name']} {item['surname']}"
        )
    election = jobs.election(cfg, job)
    before = cutoff(cfg, election)
    published = f.get("published") or doc["published"]
    if before and not (published and published < before.isoformat()):
        problems.append(
            f"published {published or 'when, not known'}: the election of"
            f" {election.day} counts only pages published before {before},"
            " the day of its last round"
        )
    return problems


def _valid_date(text: str) -> bool:
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


# --- accept -------------------------------------------------------------------


def accept(cfg: Config, job: jobs.Job, accepted: list[jobs.Accepted]) -> list[str]:
    """Merge the accepted research into ``data/curated/research/``."""
    categories = job.context["categories"]
    index = _documents(job)
    today = dt.date.today().isoformat()
    cached = cfg.curated_dir / CACHE_DIR
    cached.mkdir(parents=True, exist_ok=True)
    lines = []
    election = jobs.election(cfg, job)
    for item, out in accepted:
        path = curated_path(cfg, item["id"])
        record = researched(cfg, item["id"], election)
        if path.is_file() and not record:
            raise jobs.JobError(
                f"{path}: research of a person of another election, whose id"
                f" {item['id']} is the same"
            )
        kept = [
            f for f in record.get("findings", []) if f["category"] not in categories
        ]
        new = []
        for f in out["findings"]:
            doc = index[f["url"]]
            copy = cached / f"{doc['cache']}.html"
            if not copy.is_file():
                shutil.copyfile(job.path / DOCUMENTS_DIR / copy.name, copy)
            new.append(_curated_finding(cfg, job, f, doc))
        done_now = {c: {"date": today, "job": job.name} for c in categories}
        content = {
            "name": item["name"],
            "election": election.day.isoformat(),
            "researched": dict(
                sorted((record.get("researched", {}) | done_now).items())
            ),
            "findings": sorted(
                kept + new, key=lambda f: (f["category"], f["url"], f["quote"])
            ),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        jobs.write_json(path, content)
        found = f"findings: {len(new)}" if new else "nothing found"
        lines.append(f"{item['name']} ({item['id']}): {found}")
    return lines


def _curated_finding(
    cfg: Config, job: jobs.Job, f: Mapping[str, Any], doc: Mapping[str, str]
) -> dict[str, Any]:
    """Return the curated record of finding *f*, whose page *doc* describes."""
    return {
        "category": sources.category(f["url"], cfg.sources),
        "url": f["url"],
        "title": f.get("title") or doc["title"],
        "published": f.get("published") or doc["published"],
        "language": doc["language"] or job.context["language"],
        "cache": doc["cache"],
        "fetched": doc["fetched"],
        "via": doc["via"],
        "kind": f["kind"],
        "claim": {"en": f["claim_en"], "sk": f["claim_sk"]},
        "quote": " ".join(f["quote"].split()),
        "identity": f["identity"],
        "job": job.name,
    }


# --- agent helpers ---------------------------------------------------------------


def read(cfg: Config, job: jobs.Job, url: str, person: str | None) -> dict[str, Any]:
    """Return what an agent needs of the page *url*.

    Whether it may be cited, its metadata and the passages naming *person*
    (or the start of the text); the copy is kept for the check.
    """
    category = sources.category(url, cfg.sources)
    categories = job.context["categories"]
    if category not in categories:
        reason = (
            f"not in the job's categories ({', '.join(categories)})"
            if category
            else "not on the allowlist (or excluded or blocked)"
        )
        return {"url": url, "allowed": False, "reason": reason}
    try:
        record, text = keep(cfg, job, url)
    except cache.CacheError as e:
        return {"url": url, "allowed": True, "cached": False, "reason": str(e)}
    answer: dict[str, Any] = {
        "url": url,
        "allowed": True,
        "cached": True,
        "category": category,
        "title": record["title"],
        "published": record["published"],
        "language": record["language"],
        "characters": len(text),
    }
    items = {i["id"]: i for i in job.items}
    if person and person in items:
        p = items[person]
        answer["names_person"] = names_person(
            cache.normalize(text), p["first_name"], p["surname"]
        )
        answer["passages"] = passages(text, p["surname"])
    else:
        answer["passages"] = [text[: _PASSAGE * 2]]
    return answer


def passages(text: str, surname: str) -> list[str]:
    """Return windows of *text* around mentions of *surname*.

    Merged where they overlap, verbatim (so quotes can be copied).
    """
    plain = " ".join(text.split())
    stem = re.escape(name_stem(surname))
    spans: list[list[int]] = []
    for m in re.finditer(rf"(?<!\w){stem}", plain, re.IGNORECASE):
        start, end = max(0, m.start() - _PASSAGE), min(len(plain), m.end() + _PASSAGE)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = end
        else:
            spans.append([start, end])
        if len(spans) > _MAX_PASSAGES:
            break
    return [plain[s:e] for s, e in spans[:_MAX_PASSAGES]]


def submit(cfg: Config, job: jobs.Job, out: dict[str, Any]) -> list[str]:
    """Check one output item and, if it passes, put it into ``output.json``.

    Replaces an earlier item of the same id; returns the problems.
    """
    problems = [f"{at or '/'}: {m}" for at, m in jobs.validate(out, ITEM_SCHEMA)]
    if problems:
        return problems
    items = {i["id"]: i for i in job.items}
    if out["id"] not in items:
        return [f"{out['id']!r} is not an id of input.json"]
    problems = check(cfg, job, items[out["id"]], out)
    if problems:
        return problems
    path = job.path / jobs.OUTPUT
    with _locked(job.path / "output.lock"):
        content = json.loads(path.read_bytes()) if path.is_file() else {"items": []}
        rest = [i for i in content["items"] if i.get("id") != out["id"]]
        order = {key: n for n, key in enumerate(items)}
        content["items"] = sorted([*rest, out], key=lambda i: order.get(i.get("id"), 0))
        jobs.write_json(path, content)
    return []


def coverage(cfg: Config, election: Election, only: Iterable[str]) -> Iterator[str]:
    """Yield, per research language, the coverage of the selected persons.

    Of *election*: researched, with findings, in pending jobs, to do.
    """
    languages, places = split_only(cfg, only)
    data = candidate_data(cfg, election)
    persons = selected_persons(cfg, election, data, places)
    records = {p: researched(cfg, p, election) for p in persons}
    pending: dict[str, set[str]] = defaultdict(set)
    day = election.day.isoformat()
    for job in jobs.existing(cfg, jobs.kinds()[NAME]):
        if job.pending and job.context.get(jobs.ELECTION) == day:
            pending[job.context["language"]] |= {i["id"] for i in job.items}
    yield f"{len(persons)} candidates selected"
    for lang in languages:
        categories = cfg.sources.research[lang]
        finished = [p for p in persons if done(records[p], categories)]
        found = sum(
            any(f["category"] in categories for f in records[p].get("findings", []))
            for p in finished
        )
        waiting = len(set(persons) & pending[lang] - set(finished))
        yield (
            f"{lang}: {len(finished)} researched ({found} with findings),"
            f" {waiting} in pending jobs, {len(persons) - len(finished) - waiting} to do"
        )


_OFFICIAL = (
    "\n- `official` also covers the official website of every"
    " municipality and region; each item lists the ones of the"
    " places the person stands in (`official_sites`)."
)
"""The part of :data:`PROMPT` for jobs that search the official sites."""

_PAST = """

## As of election day

The election (its last round) was held on {day}; the site shows each
candidate as voters could know them then. Only pages published before
{day} count: give `published` for every finding (a page that shows no date
cannot be cited), and report what was known by that day, not what
happened later."""
"""The part of :data:`PROMPT` for an election other than the latest (:func:`cutoff`)."""

PROMPT = """\
# Candidate research in {language} sources

Each item of `input.json` is one candidate of {election} of {day}: name
with academic titles, first name, surname, age and stated occupation (null
and empty where the candidate lists do not give them), municipality of
residence, every candidacy (contest, ballot number, nominating parties) and
every office the person holds now. Your task: find what the allowlisted
sites say about this person, and report each relevant fact with a verbatim
quote.{past}

## Where to search

Only pages on these hosts and their subdomains count (`hosts` in
`input.json`), categories {categories}:{official}

- Search with site restrictions, e.g. `"Jozef Novák" (site:sme.sk OR
  site:pravda.sk)`; try the name with the municipality or the office too.
  Slovak names decline (Novák → Nováka, Novákovi; Nováková → Novákovej):
  search engines match the base form, pages may use another.
- Search for controversies by name too, not only for the person: the name
  with words such as kauza, obvinenie, obžaloba, súd, polícia, NAKA,
  vyšetrovanie, podozrenie, úplatok, korupcia, konflikt záujmov,
  dezinformácie, klamstvo, hoax, fact-check (in the language of the
  sources).
- A prominent person (a candidate for president, a party leader or one of
  the first names on a party's list, a minister or former minister, a
  member of parliament) has affairs that are widely known: before you
  finish, write down every scandal, investigation, allegation and
  documented falsehood you know of about them, and search for each one by
  its own words: the surname with the case's name, the other people
  involved or what it was about. Report each one an allowlisted page
  supports; say in `note` which you looked for and could not support.
  Missing a famous affair is a worse error than missing a minor career
  fact.
- Pages under a `blog` host or path are user content and never count.
- Only HTML web pages can be cited, no PDFs.

## Is it the same person?

Namesakes are common: two "Ján Kováč" can live in the same district. A hit
is about the candidate only if the source ties it to them: the
municipality, the office or candidacy, the occupation, the age, or the
party. When in doubt, leave it out. Say in `identity` what ties it (e.g.
"names him mayor of Lesné", "a lawyer from Michalovce, 52").

## What to report

Only noteworthy facts that help a voter understand what kind of person the
candidate is: what makes them stand out, for better or worse. Each as a
finding:

- `cv`: achievements and roles that set the person apart: a notable career,
  expertise, a business or organisation they built or run, initiatives or
  decisions they led and their results, awards, public activity beyond the
  routine. For a prominent person, only the main roles (offices held, the
  posts that defined their career), not every step.
- `affair`: a serious controversy, established with certainty: criminal
  proceedings against the candidate (charges, an indictment, detention, an
  investigation stated to be about their own conduct), a court decision
  against them in a matter of public relevance (a conviction, a penal
  order, a judgment that they acted unlawfully), or another very serious
  matter established by an authority or undisputed (a binding sanction for
  a conflict of interest, an audit finding serious breaches they were
  responsible for, removal from office for misconduct, a confirmed offence
  such as drunk driving).
- `dispute`: a suspicion or accusation of wrongdoing by the candidate that
  is not established: allegations of corruption, bribery, abuse of office,
  conflicts of interest, unexplained wealth, plagiarism or the like that
  the candidate denies or no authority has confirmed (a witness's
  testimony, a journalists' investigation, a criminal complaint with no
  charges, an investigation that names no charge against them, a case that
  ended in their favour: acquittal, charges dropped); statements of theirs
  that fact-checkers or the media documented as false or as
  disinformation, smears of opponents, hate speech; serious breaches of
  ethics or of the rules reported by the media; minor fines. When in doubt
  between the two, `dispute`.

Both are about the candidate's own conduct. Not a controversy, and so not
a finding at all:

- the candidate criticising someone, taking a political position, voting
  or disagreeing in an ordinary political way, or being criticised for
  their opinions: that is politics, not wrongdoing;
- what someone else did (a relative, a colleague, their party, a
  government they sat in, someone they appointed), unless the source ties
  the candidate's own act to it (they are accused, they knew and covered
  it up, they personally decided it).

For both, report what the source says, attributed ("according to the
police…", "according to the testimony of …"), never more, and note
acquittals, denials or outcomes if the source gives them.

Not:

- elections: results, votes, list positions, being elected or re-elected,
  candidacies, nominations, announcing a run, campaign events. The site
  shows the candidacies, who holds the office now and the results already;
  what a candidate said or did in a campaign counts only as a `dispute` as
  above (a documented falsehood or smear);
- holding a current office as such, or its routine (attending a ceremony,
  opening a renovated road, a council's agenda);
- private life without public relevance, opinions about the person
  without facts, bare candidate lists or memberships.

When in doubt whether a fact is noteworthy, leave it out: no finding beats
a filler finding, and "nothing found" is a valid result. Order matters
too: the most serious and widely reported matters first.

For each finding:

- `url`: the page (canonical article URL, no tracking parameters).
- `title`: the page's headline; `published`: its date (YYYY-MM-DD), if
  shown.
- `quote`: copied verbatim from the page, {min_quote}–{max_quote} characters,
  the sentence(s) that state the fact; `…` may join two passages of the same
  page in order. No paraphrase, no translation.
- `claim_en`, `claim_sk`: one neutral sentence stating what the quote
  supports, in English and in Slovak, naming the source if it is an
  allegation. At most {max_claim} characters each.
- `identity`: as above.

One fact per finding; several findings may cite the same page. Prefer the
most recent and most informative pages; three telling findings beat ten
ordinary ones.

## Output

One item per person: `id`, `queries` (the searches you ran, at least one),
`findings` (possibly empty: "nothing found" is a valid result), optionally
`note`. Report every person you searched for, including those with nothing
found.

`ems job ingest` (or `ems research submit <job>`, with an item or an array
of items as JSON on stdin) fetches and caches every cited page and rejects a finding
whose page is not allowed, cannot be fetched, does not contain the quote
verbatim, or does not name the person. `ems research read <job> <url>
--person <id>` shows whether a page can be cited and the passages that name
the person.
"""
"""Instructions of a research job; :func:`_prompt` fills in the fields."""


KIND = jobs.Kind(
    name=NAME,
    summary=(
        "research of candidates in allowlisted media and official sites, per"
        " language and constituency"
    ),
    item_schema=ITEM_SCHEMA,
    default_size=DEFAULT_SIZE,
    make=make,
    check=check,
    accept=accept,
    priorities=(PRIORITY,),
    per_election=True,
)
