"""NZ-only research instructions and schemas, without importing the reader stack."""

from dataclasses import dataclass
from importlib.resources import files

NAME = "nz-law"
SUMMARY = "Research New Zealand cases, legislation, court rules and professional conduct rules."


def prose() -> str:
    """Read the packaged instructions; no credentials or snapshot are needed."""
    return files("legal_corpus").joinpath("skills/nz-law.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Tool:
    """A consumer-neutral tool contract; the consumer supplies its implementation."""

    name: str
    description: str
    parameters: dict


_COURTS = {
    "type": "array",
    "items": {"type": "string", "enum": ["NZSC", "NZCA", "NZHC", "NZPC"]},
    "description": "Omit for all held courts.",
}
_FILTERS = {
    "kind": {"type": "string", "enum": ["cases", "legislation", "all"]},
    "courts": _COURTS,
    "since": {"type": "integer", "description": "Earliest decision year."},
    "until": {"type": "integer", "description": "Latest decision year."},
    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
}


def _schema(required: list[str], properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": required}


TOOLS = (
    Tool(
        "nz_keyword_search",
        "Search NZ judgments, Acts in force and court/conduct rules by exact terms. "
        'Put a required phrase in double quotes; prefix an excluded term with "-". '
        "`within` allows that many words between a quoted phrase's words. "
        "Search snippets are not a substitute for reading the passage in context.",
        _schema(
            ["query"],
            {"query": {"type": "string"}, "within": {"type": "integer", "minimum": 0}, **_FILTERS},
        ),
    ),
    Tool(
        "nz_semantic_search",
        "Search NZ judgments, Acts and rules by meaning, then rerank. Use a legal "
        "question or fact pattern; use keyword search for exact words. This spends "
        "a small embedding/reranking charge in addition to the chat model's tokens.",
        _schema(["query"], {"query": {"type": "string"}, **_FILTERS}),
    ),
    Tool(
        "nz_read",
        "Read a judgment's paragraphs with surroundings and footnotes, or a provision "
        "with definitions. Takes '[2007] NZSC 7 at [104]', a case name, 'NZBORA s 5', "
        "'HCR r 5.17', 'DCR r 5.17', or a bare 'r 5.17' (High Court Rules). "
        "`paragraphs` selects paragraph numbers; use the returned cursor to read on.",
        _schema(
            ["citation"],
            {
                "citation": {"type": "string"},
                "paragraphs": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                "cursor": {"type": "integer", "minimum": 1},
            },
        ),
    ),
    Tool(
        "nz_cases_citing",
        "List NZ judgments citing a case, with the citing passages. Find later "
        "treatment or how courts describe a decision whose text is not held.",
        _schema(
            ["case"],
            {
                "case": {"type": "string"},
                "courts": _COURTS,
                "since": {"type": "integer"},
                "page": {"type": "integer", "minimum": 1},
            },
        ),
    ),
    Tool(
        "nz_cases_citing_provision",
        "List judgments citing an NZ section or rule, such as 'Evidence Act 2006 s 8' "
        "or 'HCR r 5.17'. Name the instrument for conduct rules and other rules.",
        _schema(
            ["provision"],
            {
                "provision": {"type": "string"},
                "courts": _COURTS,
                "since": {"type": "integer"},
                "page": {"type": "integer", "minimum": 1},
            },
        ),
    ),
    Tool(
        "nz_case_links",
        "List a case's authorities or treatment links. `cites` gives cases it cites; "
        "the other relations report treatments recorded in the corpus, not a complete citator.",
        _schema(
            ["case", "relation"],
            {
                "case": {"type": "string"},
                "relation": {
                    "type": "string",
                    "enum": ["cites", "status", "treatment_summary", "co_cited"],
                },
            },
        ),
    ),
)
