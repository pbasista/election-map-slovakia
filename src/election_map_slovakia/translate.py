"""The ``translation`` job kind: UI strings, occupations and research, machine-translated.

Only Slovak and English UI strings are written by hand (``web/i18n/``);
every other enabled language gets them, every language but Slovak gets the
candidates' occupations, and every language the research texts in other
languages, from translation jobs (see :mod:`jobs`). Each part is translated
per target language:

- ``ui``: one job per language with every UI string not translated yet, from
  the English text (more reliable for machine translation than Slovak), with
  the Slovak one for reference, a note where the string appears and, for
  strings in tight places, a maximum length.
- ``occupations``: the occupations of ``data/build/candidates.json`` not
  translated yet, from Slovak, most frequent first, in jobs of about
  ``--size`` items (evenly split).
- ``research``: the claims of the curated research (:mod:`research`), from
  English, into every language but English and Slovak (the research agents
  write both), and its quotes, from the page's language, into every other
  language.

``--only`` takes language codes and part names (``ui``, ``occupations``,
``research``).

Accepted translations are curated in ``data/curated/translations/<lang>.json``::

    {
        "occupations": {"<Slovak occupation>": "<translation>"},
        "research": {"<claim or quote>": "<translation>"},
        "ui": {"<key>": {"src": "<English text translated>", "text": "<translation>"}},
    }

A UI translation whose ``src`` is not the current English text is stale and
counts as missing: ``build`` falls back to English for it, and ``make``
makes a job for it again. Occupations and research texts are keyed by their
text, so a changed one is simply a new one. Output item ids are the UI key,
or for the others :func:`occupation_id` of the text.

The deterministic checks of an output item (:func:`problems`): not empty;
the same ``{placeholders}`` and markup as the source; a length within bounds
of the source's (and within ``max_length`` where given); in the script of the
target language (``languages.toml``), where words in another script are
allowed only if the source has them (names, abbreviations); for Czech and
Ukrainian, none of the letters that betray Slovak or Russian; and not a copy
of the source (or, for UI strings, of the Slovak reference) unless marked
``identical`` and short.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from election_map_slovakia import candidates, jobs, research
from election_map_slovakia.config import Config

NAME = "translation"
UI_DIR = Path("web") / "i18n"
"""The hand-written UI strings, relative to the project root."""
CURATED_DIR = "translations"
SOURCE = "en"
"""The language UI strings are translated from."""
REFERENCE = "sk"
"""The language occupations are translated from, and the UI's reference."""
UI = "ui"
OCCUPATIONS = "occupations"
RESEARCH = "research"
PARTS = (UI, OCCUPATIONS, RESEARCH)
DEFAULT_SIZE = 900
_ID_LENGTH = 10
_PLACEHOLDER = re.compile(r"\{\w+\}")
_MARKUP = re.compile(r"<[^>]*>|&#?\w+;")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# Shorter translations happen (abbreviations), longer ones more (an
# abbreviation spelled out); outside these bounds something else happened.
_MIN_RATIO = 0.25
_MAX_RATIO = 3.0
_SLACK = 25
_MAX_IDENTICAL_WORDS = 6
_SCRIPTS = {"Latn": "LATIN", "Cyrl": "CYRILLIC"}
# Letters of a neighbouring language that the target language does not use:
# Slovak in Czech, Russian in Ukrainian.
_FOREIGN_LETTERS = {"cs": "äôľĺŕ", "uk": "ыэъё"}


@dataclass(frozen=True)
class Guide:
    """How to translate into one language."""

    name: str
    """The language in English, as the prompt names it."""
    text: str
    """The language-specific part of the prompt (Markdown)."""


GUIDES: dict[str, Guide] = {
    "sk": Guide(
        "Slovak",
        """\
- Standard Slovak, as Slovak news media write it. Not Czech: Slovak words
  and spelling (`ä`, `ô`, `ľ`, `ĺ`, `ŕ` where Slovak has them).
- Slovak names of places and institutions in Slovakia (the Hungarian or
  other name of a Slovak municipality becomes its official Slovak name).""",
    ),
    "en": Guide(
        "English",
        """\
- British spelling, as in the site's English texts ("neighbouring",
  "licence" as a noun).
- English has no gender forms for most occupations: `učiteľ` and `učiteľka`
  are both "teacher"; do not add "female". Keep gender words where they are
  the occupation itself (`pôrodná asistentka` → "midwife").
- Usual equivalents: `SZČO`, `živnostník` → "self-employed" (or "sole
  trader"); `dôchodca`/`dôchodkyňa` → "pensioner"; `výsluhový dôchodca` →
  "retired on a service pension"; `nezamestnaný/á` → "unemployed"; `starosta
  (obce)` → "mayor"; `primátor` → "mayor (of a city)"; `konateľ (spoločnosti)`
  → "company director"; `SHR` → "self-employed farmer"; `ZŠ` → "primary
  school"; `MŠ` → "kindergarten"; `ZUŠ` → "primary art school"; `SOŠ` →
  "secondary vocational school"; `OcÚ`, `OÚ`, `MsÚ` → "municipal office";
  `MsZ`, `OZ` (council) → "town council" / "municipal council"; `OZ`
  (association) → "civic association"; `VÚC` → "self-governing region";
  `PZ SR` → "Police Force"; `HaZZ` → "Fire and Rescue Service".""",
    ),
    "cs": Guide(
        "Czech",
        """\
- Standard Czech. Watch for Slovak creeping in: no `ä`, `ô`, `ľ`, `ĺ`, `ŕ`
  (the check rejects them outside names), Czech words for false friends
  (`vodič` → "řidič", `dôchodca` → "důchodce", `konateľ` → "jednatel",
  `úradník` → "úředník").
- Keep the gender of the Slovak form: `učiteľka` → "učitelka",
  `dôchodkyňa` → "důchodkyně", `nezamestnaná` → "nezaměstnaná".
- Czech equivalents: `SZČO` → "OSVČ"; `živnostník` → "živnostník";
  `SHR` → "samostatně hospodařící rolník"; `ZŠ`, `MŠ`, `ZUŠ`, `SOŠ` stay
  (Czech uses the same abbreviations); `OcÚ`/`OÚ` → "obecní úřad", `MsÚ`
  → "městský úřad"; `starosta`, `primátor`, `okres`, `kraj` stay.
- Formal address (vykání).""",
    ),
    "hu": Guide(
        "Hungarian",
        """\
- Standard Hungarian. Hungarian has no grammatical gender: translate
  feminine forms with the neutral noun (`dôchodkyňa` → "nyugdíjas"), except
  where a feminine word is the usual one (`zdravotná sestra` → "ápolónő",
  `učiteľka v materskej škole` → "óvónő").
- Equivalents: `SZČO`, `živnostník` → "egyéni vállalkozó"; `starosta` →
  "polgármester"; `primátor` → "polgármester" (of a city); `konateľ` →
  "ügyvezető"; `okres` → "járás"; `kraj` → "kerület" / "megye" as used by
  Hungarian media in Slovakia; `ZŠ` → "alapiskola"; `MŠ` → "óvoda".
- Place names stay in their official Slovak form, as everywhere on the site
  (do not replace them with Hungarian names).
- Polite, impersonal address as on public-service sites.""",
    ),
    "pl": Guide(
        "Polish",
        """\
- Standard Polish. Keep the gender of the Slovak form: `učiteľka` →
  "nauczycielka", `dôchodca` → "emeryt", `dôchodkyňa` → "emerytka".
- False friend: Slovak `starosta` is the head of a municipality, Polish
  "wójt" (village) or "burmistrz" (town); Polish "starosta" heads a powiat
  and is wrong here. `primátor` → "prezydent miasta" / "burmistrz".
- Equivalents: `SZČO`, `živnostník` → "przedsiębiorca" / "osoba prowadząca
  działalność gospodarczą" (prefer the shorter); `konateľ` → "prezes
  zarządu spółki" or "członek zarządu"; `okres` → "powiat"; `kraj` →
  "kraj"; `ZŠ` → "szkoła podstawowa".
- Polite, impersonal address as on public-service sites.""",
    ),
    "uk": Guide(
        "Ukrainian",
        """\
- Standard Ukrainian, Cyrillic script. Not Russian: no `ы`, `э`, `ъ`, `ё`
  (the check rejects them outside names); use Ukrainian words, not Russian
  ones in Ukrainian spelling.
- Keep the gender of the Slovak form: `učiteľka` → "вчителька", `dôchodca`
  → "пенсіонер", `dôchodkyňa` → "пенсіонерка".
- Equivalents: `SZČO`, `živnostník` → "ФОП" or "підприємець"; `starosta`
  → "староста"; `primátor` → "мер"; `konateľ` → "директор компанії" /
  "керівник товариства"; `okres` → "округ"; `kraj` → "край".
- Names of people, places and companies stay in Latin script as in the
  source (the site lists them in Slovak); abbreviations without a Ukrainian
  equivalent may stay too.
- Address the reader with "ви".""",
    ),
    "de": Guide(
        "German",
        """\
- Standard German (Germany/Austria neutral). Keep the gender of the Slovak
  form: `učiteľka` → "Lehrerin", `dôchodca` → "Rentner", `dôchodkyňa` →
  "Rentnerin". No gender-neutral forms with `*` or `:`.
- Equivalents: `SZČO`, `živnostník` → "Selbstständiger" / "Selbstständige";
  `starosta` → "Bürgermeister(in)"; `primátor` → "Oberbürgermeister(in)";
  `konateľ` → "Geschäftsführer(in)"; `okres` → "Bezirk"; `kraj` → "Kraj"
  (Slovak region; "Region" where it reads better); `ZŠ` → "Grundschule".
- Nouns capitalized as German requires, even where the Slovak is lower case.
- Address the reader with "Sie".""",
    ),
    "rue": Guide(
        "Rusyn",
        """\
- Rusyn as codified in Slovakia in 1995 (the Prešov standard), in Cyrillic,
  as written by Rusyn media and schools in Slovakia and on the Rusyn
  Wikipedia (rue.wikipedia.org). This is neither Ukrainian nor Russian: use
  Rusyn spelling and words (e.g. "Словеньско", "Русиньскый", "обець"),
  `ы` where Rusyn has it. If unsure of a word, look it up on
  rue.wikipedia.org; if Rusyn has no own term, use the one Rusyn texts in
  Slovakia borrow, in Cyrillic.
- The site's name in Rusyn is "Волебна мапа Словеньска".
- Keep the gender of the Slovak form (`učiteľka` → feminine).
- Names of people, places and companies stay in Latin script as in the
  source; Slovak abbreviations without a Rusyn equivalent may stay too.""",
    ),
    "rmc": Guide(
        "Romani",
        """\
- Carpathian (Slovak) Romani in the standard used in Slovakia, Latin script
  with Slovak-style letters: `č`, `š`, `ž`, `ď`, `ť`, `ľ`, `ň`, `dž`, `dz`,
  `ch`, aspirates `kh`, `ph`, `th`, `čh`, long vowels `á é í ó ú`. Not the
  orthography of Vlax or other Romani varieties.
- The site's name in Romani is "Voľbengeri mapa Slovensko".
- Where Romani has no established word (offices, institutions, many
  occupations), use the Slovak word with Romani grammar, as Romani texts in
  Slovakia do; prefer being understood over purism. Never leave a whole
  string in Slovak.
- Keep the gender of the Slovak form where Romani distinguishes it.""",
    ),
}

_COMMON = """\
# Translation into {language}

You translate {what} for "Election Map Slovakia" (in Slovak "Volebná mapa
Slovenska"), a non-commercial website that shows the constituencies and
candidates of the Slovak municipal and regional elections of 24 October 2026.
Readers are voters in Slovakia whose language is {language}. The site
discloses that these translations are machine-made.

## Rules for every item

- Translate `source` into {language} (`{lang}`). Output only the
  translation: no quotes around it, no explanations, no alternatives.
- Placeholders in braces, such as `{{name}}`, `{{n}}`, `{{site}}`, are filled
  in by the site: keep each one exactly as written (same name, in braces,
  never translated), as often as in the source, placed where the grammar of
  {language} needs it. `{{site}}` becomes the site's name in {language}.
- Keep markup (`<…>`, `&…;`) exactly, if any.
- Keep names of people, places, companies, organisations, products and
  licences as in the source (e.g. "MV SR", "ÚGKK SR", "ZBGIS", "CC BY 4.0",
  "CC0", "EUPL-1.2", "Natural Earth", "Leaflet", "konspiratori.sk",
  "Reuters Institute Digital News Report"); translate the generic words
  around them.
- Write the language's own punctuation and quotation marks; keep
  numbers and dates as they are.
- `identical`: if the right translation is exactly the source text (a
  name, an abbreviation, or a word that is the same in {language}), set
  `"identical": true` on the item. Without it, a translation equal to the
  source{reference} is rejected as untranslated.
- If you cannot translate an item, leave it out of `output.json`.

{part}

## {language}

{guide}

## Output

Write `output.json` here, as README.md describes: `{{"items": [{{"id": …,
"text": …}}, …]}}`, one item per input item, with its `id` unchanged and
`text` the translation (plus `"identical": true` where it applies). The
ingest check rejects an item whose placeholders or markup differ from the
source, that is empty, much shorter or longer than the source (or longer
than `max_length`), or in another script than {language}'s ({script}),
except for words that are in the source as they are.
"""

_UI_PART = """\
## The items: interface strings

Each item of `input.json` is one string of the site's interface: `source`
is the English text (translate this), `sk` the Slovak original for
reference, `note` where it appears, and `max_length`, where present, the
most characters that fit (count the placeholders as written).

- Translate meaning, not words; it must read as written in {language}.
- Keep the terms consistent across items: the same Slovak institution or
  contest has the same name everywhere. "okres" (district) and "kraj"
  (region) are Slovak administrative units; English keeps the Slovak words.
  In `{{name}} kraj` the `{{name}}` is the Slovak adjective of the region
  (e.g. "Bratislavský"); in `okres {{name}}` it is the okres name (e.g.
  "Malacky").
- Contest names follow the Slovak law: "mayor" is the starosta (primátor in
  cities), "municipal council" the obecné zastupiteľstvo, "self-governing
  region" the samosprávny kraj.
- Address the reader as public-service websites in {language} do."""

_OCCUPATIONS_PART = """\
## The items: occupations

Each item of `input.json` is one occupation as a candidate stated it on the
official Slovak candidate list (`source`, in Slovak). The site shows the
translation next to the candidate's name, with the Slovak original
available.

- Translate it as a short occupation entry, lower case where {language}
  allows it (as the Slovak is), without adding anything.
- Grammatical gender matters: the Slovak form tells whether the candidate
  is a man (`učiteľ`, `dôchodca`) or a woman (`učiteľka`, `dôchodkyňa`).
  Keep it wherever {language} marks gender.
- Spell out Slovak abbreviations the reader would not know with the usual
  equivalent in {language} (see below); keep those that are international
  (`IT`, `CNC`, `HR`) and legal forms of companies (`s. r. o.`, `a. s.`).
  Ambiguous ones by context: `OZ` is a civic association
  (občianske združenie) or the municipal council (obecné zastupiteľstvo);
  `PO` a legal entity or fire protection.
- Common Slovak abbreviations: `SZČO` self-employed person, `SHR`
  self-employed farmer, `ZŠ` primary school, `MŠ` kindergarten, `ZUŠ`
  primary art school, `SOŠ` secondary vocational school, `SŠ` secondary
  school, `VŠ` university, `BOZP` occupational health and safety, `SBS`
  private security service, `STK` vehicle inspection station, `MsZ`/`MZ`
  town council, `MsÚ`/`MÚ` town office, `OcÚ`/`OÚ` municipal office, `VÚC`
  self-governing region, `ÚPSVaR` labour office, `ZŤP` severely disabled,
  `THP` technical and administrative staff, `MHD` public transport, `ČOV`
  sewage treatment plant, `MOaPS` local / regional welfare office.
- Keep names of employers, schools, towns and organisations as in the
  source; translate generic words around them."""

_RESEARCH_PART = """\
## The items: claims and quotes about candidates

Each item of `input.json` is a text the site shows about a candidate,
researched from news media and official sites: either a one-sentence claim
(written in English) or a verbatim quote from the cited page, in the
page's language (`source_language` says which). The site shows the
translation next to the original.

- Translate faithfully and neutrally, sentence for sentence, without adding,
  softening or sharpening anything: an allegation stays an allegation
  ("according to the police…"), a suspicion a suspicion.
- Keep names of people, municipalities, parties, companies, courts and
  institutions as in the source; translate generic words around them.
- Keep numbers, amounts, dates and quotation marks' meaning."""


def guide(code: str) -> Guide:
    """Return the translation guide of language *code*."""
    if code not in GUIDES:
        raise jobs.JobError(f"{NAME}: no translation guidance for {code!r}")
    return GUIDES[code]


# --- curated data -----------------------------------------------------------


@dataclass
class Curated:
    """``data/curated/translations/<lang>.json``."""

    ui: dict[str, dict[str, str]] = field(default_factory=dict)
    occupations: dict[str, str] = field(default_factory=dict)
    research: dict[str, str] = field(default_factory=dict)

    def ui_strings(self, source: Mapping[str, str]) -> dict[str, str]:
        """Return key → translation of the UI strings still current in *source*."""
        return {
            key: entry["text"]
            for key, entry in self.ui.items()
            if source.get(key) == entry["src"]
        }


def curated_path(cfg: Config, code: str) -> Path:
    """Return the curated translations file of language *code*."""
    return cfg.curated_dir / CURATED_DIR / f"{code}.json"


def load(cfg: Config, code: str) -> Curated:
    """Return the curated translations of language *code* (empty if none)."""
    path = curated_path(cfg, code)
    if not path.is_file():
        return Curated()
    content = json.loads(path.read_bytes())
    return Curated(
        content.get(UI, {}), content.get(OCCUPATIONS, {}), content.get(RESEARCH, {})
    )


def save(cfg: Config, code: str, curated: Curated) -> None:
    """Write the curated translations of language *code*."""
    content: dict[str, Any] = {OCCUPATIONS: curated.occupations, UI: curated.ui}
    if curated.research:
        content[RESEARCH] = curated.research
    jobs.write_json(curated_path(cfg, code), content)


def research_texts(cfg: Config) -> list[tuple[str, str]]:
    """Return (text, its language) of every curated research claim and quote.

    Claims count in English, their translation source; most frequent first
    would not mean anything here, so in file order, each text once.
    """
    root = cfg.curated_dir / research.CURATED_DIR
    seen: dict[str, str] = {}
    for path in sorted(root.glob("*/*.json")):
        for f in json.loads(path.read_bytes()).get("findings", []):
            seen.setdefault(f["claim"]["en"], SOURCE)
            seen.setdefault(f["quote"], f["language"])
    return list(seen.items())


def research_targets(cfg: Config, text_language: str) -> list[str]:
    """Return the languages a research text in *text_language* goes into.

    The agents write claims in English and Slovak, so an English text (a
    claim) needs neither.
    """
    skip = {SOURCE, REFERENCE} if text_language == SOURCE else {text_language}
    return [c for c in cfg.languages.codes if c not in skip]


def ui_source(cfg: Config, code: str) -> dict[str, str]:
    """Return the hand-written UI strings of language *code*."""
    return json.loads((cfg.root / UI_DIR / f"{code}.json").read_bytes())


def hand_written(cfg: Config) -> frozenset[str]:
    """Return the languages whose UI strings are written by hand."""
    return frozenset(p.stem for p in (cfg.root / UI_DIR).glob("*.json"))


def occupation_counts(data: Mapping[str, Any]) -> Counter[str]:
    """Return occupation → candidacies stating it, of ``candidates.json``."""
    return Counter(c["occupation"] for c in data["candidacies"] if c["occupation"])


def occupation_id(text: str) -> str:
    """Return the job item id of an occupation: a hash of its text."""
    return hashlib.sha256(text.encode()).hexdigest()[:_ID_LENGTH]


# --- make ---------------------------------------------------------------------

_NOTES = (
    ("app.title", "browser tab title of the page"),
    ("app.description", "page description for search engines"),
    ("app.noscript", "shown when JavaScript is off"),
    (
        "app.tagline",
        "subtitle under the site name in the header; {date} is the election"
        " date, already formatted",
    ),
    ("nav.language", "heading of the language menu"),
    (
        "nav.switch",
        "tooltip and accessible label of the language button; {current} and"
        " {next} are language names",
    ),
    ("help.", "help button and its popover"),
    (
        "theme.button",
        "tooltip of the appearance button; {mode} is one of the option names"
        " (theme.system, theme.light, theme.dark)",
    ),
    ("theme.", "appearance menu (light or dark colours)"),
    ("disclaimer.short", "short disclaimer in the help popover"),
    ("disclaimer.more", "link from the help popover to the About dialog"),
    ("disclaimer.", "item of the Disclaimers list in the About dialog"),
    (
        "translation.pending",
        "notice on the pages of a language whose translation is incomplete",
    ),
    ("layers.button", "tooltip of the boundaries button, which opens the menu"),
    ("layers.oz_", "entry of the map legend"),
    ("layers.auto", "note in the boundaries menu under its checkboxes"),
    (
        "layers.",
        "boundaries menu: its title and the names of the constituency"
        " overlays it switches on and off",
    ),
    (
        "map.attribution",
        "attribution line at the bottom of the map; keep the names, © and"
        " licence identifiers",
    ),
    ("map.obvod", "label on the map of the constituency number {n}; very short"),
    ("map.", "map: accessible label and zoom buttons"),
    ("country.", "name of a country, a label on the map: the usual short name"),
    ("panel.", "side panel with the ballots"),
    ("error.", "error message"),
    ("search.type.", "short tag after a search result saying what it is"),
    (
        "search.okres",
        "subtitle of a search result: the okres (district) a place is in;"
        " {name} is the okres name, e.g. Malacky",
    ),
    ("search.person", "a candidate in search results: {name}, {age} in years"),
    ("search.", "search box and its results"),
    (
        "place.kraj",
        "subtitle of a place; {name} is the Slovak adjective naming the kraj"
        " (region), e.g. Bratislavský",
    ),
    ("place.", "subtitle or message of the place shown in the panel"),
    ("ballots.", "the ballots of a place"),
    (
        "contest.",
        "heading or details of one contest (ballot); {name} is a municipality"
        " or city name, {kraj} the Slovak adjective of the region, {n} a number",
    ),
    ("council.", "notice above the council ballots of a municipality"),
    (
        "candidate.occupation_sk",
        "tooltip of a translated occupation, and a line on the candidate card;"
        " {text} is the occupation as written in Slovak",
    ),
    ("candidate.", "line of a candidate on a ballot"),
    ("card.", "candidate card"),
    ("research.", "candidate card, research section"),
    ("about.category.", "name of a group of news sources in the About dialog"),
    ("about.", "About dialog"),
)
_LIMITS = (
    ("map.obvod", 12),
    ("card.back", 16),
    ("panel.close", 16),
    ("candidate.age", 16),
    ("nav.language", 20),
    ("theme.light", 20),
    ("theme.dark", 20),
    ("map.zoom", 24),
    ("theme.title", 24),
    ("layers.title", 24),
    ("search.type.", 24),
    ("country.", 28),
    ("theme.system", 30),
    ("search.placeholder", 34),
    ("disclaimer.more", 34),
    ("app.tagline", 60),
)


def _by_prefix(key: str, table: Iterable[tuple[str, Any]]) -> Any:
    """Return the value of the first entry whose key or prefix *key* matches."""
    return next(
        (
            value
            for prefix, value in table
            if key == prefix or (prefix.endswith((".", "_")) and key.startswith(prefix))
        ),
        None,
    )


def ui_item(key: str, source: str, reference: str) -> dict[str, Any]:
    """Return the job item of UI string *key*."""
    item: dict[str, Any] = {"id": key, "source": source, "sk": reference}
    note = _by_prefix(key, _NOTES)
    if note:
        item["note"] = note
    limit = _by_prefix(key, _LIMITS)
    if limit:
        item["max_length"] = max(limit, len(source))
    return item


@dataclass(frozen=True)
class _Selection:
    langs: tuple[str, ...]
    parts: tuple[str, ...]


def _select(cfg: Config, only: Iterable[str]) -> _Selection:
    codes = list(cfg.languages.codes)
    only = list(only)
    unknown = [o for o in only if o not in codes and o not in PARTS]
    if unknown:
        raise jobs.JobError(
            f"{NAME}: --only {', '.join(unknown)}: not a language"
            f" ({', '.join(codes)}) or part ({', '.join(PARTS)})"
        )
    langs = [c for c in codes if c in only] or codes
    parts = [p for p in PARTS if p in only] or list(PARTS)
    return _Selection(tuple(langs), tuple(parts))


def _pending_ids(pending: Iterable[jobs.Job]) -> set[tuple[str, str, str]]:
    return {
        (job.context["lang"], job.context["part"], item["id"])
        for job in pending
        for item in job.items
    }


def make(cfg: Config, options: jobs.MakeOptions) -> list[jobs.Batch]:
    """Return the translation jobs still to do; see the module doc."""
    selection = _select(cfg, options.only)
    pending = _pending_ids(options.pending)
    own = hand_written(cfg)
    source, reference = ui_source(cfg, SOURCE), ui_source(cfg, REFERENCE)
    built = cfg.build_dir / candidates.OUTPUT_FILE
    counts: Counter[str] = Counter()
    if OCCUPATIONS in selection.parts:
        if not built.is_file():
            raise jobs.JobError(f"{built} missing; run `ems candidates` first")
        counts = occupation_counts(json.loads(built.read_bytes()))
    texts = research_texts(cfg) if RESEARCH in selection.parts else []
    batches = []
    for code in selection.langs:
        guide(code)
        curated = load(cfg, code)
        if UI in selection.parts and code not in own:
            done = curated.ui_strings(source)
            items = [
                ui_item(key, text, reference[key])
                for key, text in source.items()
                if key not in done and (code, UI, key) not in pending
            ]
            if items:
                batches.append(_batch(cfg, code, UI, items))
        if OCCUPATIONS in selection.parts and code != REFERENCE:
            todo = [
                text
                for text, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                if text not in curated.occupations
                and (code, OCCUPATIONS, occupation_id(text)) not in pending
            ]
            n = math.ceil(len(todo) / options.size)
            for i in range(n):
                chunk = todo[len(todo) * i // n : len(todo) * (i + 1) // n]
                items = [{"id": occupation_id(t), "source": t} for t in chunk]
                batches.append(_batch(cfg, code, OCCUPATIONS, items))
        todo_research = [
            {"id": occupation_id(t), "source": t, "source_language": lang}
            for t, lang in texts
            if code in research_targets(cfg, lang)
            and t not in curated.research
            and (code, RESEARCH, occupation_id(t)) not in pending
        ]
        for start in range(0, len(todo_research), options.size):
            chunk = todo_research[start : start + options.size]
            batches.append(_batch(cfg, code, RESEARCH, chunk))
    return batches


def _batch(
    cfg: Config, code: str, part: str, items: list[dict[str, Any]]
) -> jobs.Batch:
    g = guide(code)
    script = _script(cfg, code)
    what, part_text, label, source_lang = {
        UI: ("the interface of a website", _UI_PART, "UI strings", SOURCE),
        OCCUPATIONS: (
            "candidates' occupations",
            _OCCUPATIONS_PART,
            "occupations",
            REFERENCE,
        ),
        # Per item: claims are English, quotes in their page's language.
        RESEARCH: (
            "what news media say about candidates",
            _RESEARCH_PART,
            "research texts",
            "various",
        ),
    }[part]
    prompt = _COMMON.format(
        language=g.name,
        lang=code,
        what=what,
        part=part_text.format(language=g.name),
        guide=g.text,
        script={"Latn": "Latin", "Cyrl": "Cyrillic"}.get(script, script),
        reference=" (or to the Slovak `sk`)" if part == UI else "",
    )
    return jobs.Batch(
        items=items,
        prompt=prompt,
        title=f"{len(items)} {label} into {g.name}",
        context={
            "lang": code,
            "language": g.name,
            "part": part,
            "source_language": source_lang,
        },
    )


# --- check and accept ---------------------------------------------------------

ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "text"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "the id of the input item"},
        "text": {"type": "string", "minLength": 1, "description": "the translation"},
        "identical": {
            "type": "boolean",
            "description": "true if the translation is the source text unchanged"
            " on purpose",
        },
    },
}


def _letters_by_script(text: str) -> dict[str, list[str]]:
    """Return script (``LATIN``, ``CYRILLIC``, …) → the words written in it."""
    out: dict[str, list[str]] = {}
    for word in _WORD.findall(text):
        for ch in word:
            if ch.isalpha():
                script = unicodedata.name(ch, "UNKNOWN").split(" ", 1)[0]
                out.setdefault(script, []).append(word)
                break
    return out


def _normalized(text: str) -> str:
    # Case stays: German capitalises nouns, so "Architekt" for "architekt" is
    # a translation, not a copy.
    return " ".join(text.split())


def problems(
    source: str,
    text: str,
    *,
    lang: str,
    script: str,
    reference: str | None = None,
    identical: bool = False,
    max_length: int | None = None,
) -> list[str]:
    """Return what is wrong with *text* as the translation of *source*.

    *script* is the ISO 15924 code of the target language; *reference* the
    Slovak text of a UI string, which must not be copied either.
    """
    text = text.strip()
    if not text:
        return ["empty"]
    known = set(_WORD.findall(source)) | set(_WORD.findall(reference or ""))
    copies = [source, *([reference] if reference else [])]
    return [
        *_form_problems(source, text, max_length),
        *_script_problems(text, known, lang, script),
        *_copy_problems(text, copies, identical),
    ]


def _form_problems(source: str, text: str, max_length: int | None) -> Iterator[str]:
    placeholders = sorted(_PLACEHOLDER.findall(source))
    if sorted(_PLACEHOLDER.findall(text)) != placeholders:
        yield (
            f"placeholders {sorted(_PLACEHOLDER.findall(text))} differ from the"
            f" source's {placeholders}"
        )
    if sorted(_MARKUP.findall(text)) != sorted(_MARKUP.findall(source)):
        yield "markup differs from the source's"
    if "\n" in text:
        yield "contains a line break"
    bare = len(_PLACEHOLDER.sub("", text))
    src = len(_PLACEHOLDER.sub("", source))
    if bare < _MIN_RATIO * src - 2 or bare > _MAX_RATIO * src + _SLACK:
        yield f"{bare} characters for a source of {src}"
    if max_length is not None and len(text) > max_length:
        yield f"{len(text)} characters, at most {max_length} fit"


def _script_problems(
    text: str, known: set[str], lang: str, script: str
) -> Iterator[str]:
    """Yield words in the wrong script or with letters foreign to *lang*.

    Words of the source (*known*) are names or abbreviations kept as written.
    """
    wanted = _SCRIPTS.get(script)
    for name, words in _letters_by_script(text).items():
        foreign = sorted({w for w in words if w not in known})
        if name != wanted and foreign:
            yield f"not in {script} script: {', '.join(foreign[:5])}"
    letters = set(_FOREIGN_LETTERS.get(lang, ""))
    odd = sorted(
        {w for w in _WORD.findall(text) if w not in known and set(w.lower()) & letters}
    )
    if odd:
        yield f"letters foreign to {lang}: {', '.join(odd[:5])}"


def _copy_problems(text: str, copies: list[str], identical: bool) -> Iterator[str]:
    if not any(_normalized(text) == _normalized(c) for c in copies):
        return
    if not identical:
        yield (
            "same as the source (or the Slovak reference): translate it, or set"
            ' "identical": true if it is right unchanged'
        )
    elif len(text.split()) > _MAX_IDENTICAL_WORDS:
        yield "marked identical, but too long to be a name or abbreviation"


def _script(cfg: Config, code: str) -> str:
    return next(lang.script for lang in cfg.languages.languages if lang.code == code)


def check(
    cfg: Config, job: jobs.Job, item: dict[str, Any], out: dict[str, Any]
) -> list[str]:
    """Return the problems of output item *out* for input *item*."""
    code = job.context["lang"]
    return problems(
        item["source"],
        out["text"],
        lang=code,
        script=_script(cfg, code),
        reference=item.get("sk"),
        identical=out.get("identical", False),
        max_length=item.get("max_length"),
    )


def accept(cfg: Config, job: jobs.Job, accepted: list[jobs.Accepted]) -> list[str]:
    """Merge the accepted translations into the curated file of the language."""
    code, part = job.context["lang"], job.context["part"]
    curated = load(cfg, code)
    for item, out in accepted:
        text = out["text"].strip()
        if part == UI:
            curated.ui[item["id"]] = {"src": item["source"], "text": text}
        elif part == OCCUPATIONS:
            curated.occupations[item["source"]] = text
        else:
            curated.research[item["source"]] = text
    save(cfg, code, curated)
    path = curated_path(cfg, code).relative_to(cfg.root)
    return [f"{len(accepted):,} {part} translations into {code} in {path}"]


KIND = jobs.Kind(
    name=NAME,
    summary=(
        "UI strings, occupations and research claims and quotes into the other"
        " languages"
    ),
    item_schema=ITEM_SCHEMA,
    default_size=DEFAULT_SIZE,
    make=make,
    check=check,
    accept=accept,
)
