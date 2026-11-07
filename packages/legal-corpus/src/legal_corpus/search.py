"""
`keyword_search` and `semantic_search` (research/0004 §2, 0010 decision 1).

Two tools, not one fused search, so the model chooses and the UI shows which
search found what. They share everything after retrieval:

* **priors**: a syllabus reading, a Supreme Court decision and a much-cited case
  rank higher, because those are what an NCA marker expects;
* **filters**: kind (cases, legislation), courts, legislation jurisdiction and
  years. Tier B legislation (the provinces, federal regulations) is searched
  only when a jurisdiction asks for it (research/0002 as revised by 0010);
* **grouping and bounds**: at most SEARCH_MAX_CASES documents, each with at most
  SEARCH_SNIPPETS_PER_CASE snippets, every snippet labelled with who wrote it,
  so a dissent is visible before it is read.
"""

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from lancedb.query import BooleanQuery, MatchQuery, Occur, PhraseQuery
from legal_core.citations import names_rules

from legal_corpus.constants import (
    SEARCH_CANDIDATES,
    SEARCH_MAX_CASES,
    SEARCH_SNIPPETS_PER_CASE,
    SNIPPET_CHARS,
    VECTOR_NPROBES,
    VECTOR_REFINE_FACTOR,
)
from legal_corpus.snapshot import Corpus, _quote

logger = logging.getLogger(__name__)

# Legislation jurisdictions as the tools accept them, and the datasets they mean.
JURISDICTIONS = {
    "federal": ("LEGISLATION-FED", "CONSTITUTION"),
    "federal-regulations": ("REGULATIONS-FED",),
    **{
        code.lower(): (f"LEGISLATION-{code}",)
        for code in ("AB", "BC", "MB", "NB", "NL", "NS", "NT", "ON", "PE", "QC", "SK", "YT")
    },
}
_COLUMNS = [
    "id",
    "kind",
    "doc_id",
    "number",
    "section",
    "unit",
    "heading",
    "note",
    "segment_kind",
    "segment_authors",
    "court",
    "year",
    "tier",
    "title",
    "syllabus",
    "text",
]
_QUOTED = re.compile(r'-?"([^"]+)"|-?“([^”]+)”')


@dataclass
class Filters:
    kind: str = "all"  # "cases", "legislation", "commentary" or "all"
    courts: list[str] = field(default_factory=list)
    jurisdiction: str = ""
    since: int | None = None
    until: int | None = None

    def where(self) -> str:
        """The filter as a Lance SQL predicate."""
        if self.jurisdiction:
            key = self.jurisdiction.strip().lower().replace(" ", "-")
            datasets = JURISDICTIONS.get(key, ("unknown",))
            legislation = f"court in ({', '.join(_quote(d) for d in datasets)})"
        else:
            legislation = "tier = 'A'"
        cases = "kind = 'case'"
        if self.courts:
            cases += f" and court in ({', '.join(_quote(c.upper()) for c in self.courts)})"
        if self.since:
            cases += f" and year >= {int(self.since)}"
        if self.until:
            cases += f" and year <= {int(self.until)}"
        clauses = {
            "cases": cases,
            "legislation": f"kind = 'provision' and {legislation}",
            "commentary": "kind = 'commentary'",
        }
        if self.kind == "all":
            return " or ".join(f"({clause})" for clause in clauses.values())
        return clauses[self.kind]


@dataclass
class Hit:
    row: dict
    score: float


def parse_keyword_query(query: str) -> tuple[list[str], list[str], str]:
    """
    Split a keyword query into (required phrases, excluded words or phrases, other words).

    `"pith and substance" -immunity paramountcy` requires the phrase, excludes
    "immunity" and ranks by "paramountcy". Straight and curly quotes both work.
    """
    phrases, excluded = [], []
    for match in _QUOTED.finditer(query):
        text = match.group(1) or match.group(2)
        (excluded if match.group(0).startswith("-") else phrases).append(text)
    rest = _QUOTED.sub(" ", query)
    words = []
    for word in rest.split():
        if word.startswith("-") and len(word) > 1:
            excluded.append(word[1:])
        elif word.upper() not in {"AND", "OR", "NOT"}:
            words.append(word)
    return phrases, excluded, " ".join(words)


def _fts_query(query: str, within: int):
    phrases, excluded, words = parse_keyword_query(query)
    if not phrases and not excluded:
        return MatchQuery(words, "body")
    clauses = [(Occur.MUST, PhraseQuery(p, "body", slop=max(within, 0))) for p in phrases]
    clauses += [(Occur.MUST_NOT, MatchQuery(e, "body")) for e in excluded]
    if words:
        clauses.append((Occur.SHOULD if phrases else Occur.MUST, MatchQuery(words, "body")))
    return BooleanQuery(clauses)


def _highlight_terms(query: str) -> list[str]:
    phrases, _, words = parse_keyword_query(query)
    return [p.lower() for p in phrases] + [w.lower() for w in words.split() if len(w) > 3]


def snippet(text: str, terms: list[str], length: int = SNIPPET_CHARS) -> str:
    """`length` characters of `text`, centred on the first term that occurs in it."""
    lowered = text.lower()
    positions = [lowered.find(t) for t in terms if t and lowered.find(t) >= 0]
    start = max(0, min(positions) - length // 3) if positions else 0
    piece = text[start : start + length].strip()
    return ("…" if start else "") + piece + ("…" if start + length < len(text) else "")


def _prior(row: dict, citing: dict[str, int], apex: str) -> float:
    """Multiplier for a candidate: the spine first, then the apex court, then citation count."""
    weight = 1.0
    if row["syllabus"]:
        weight += 0.35
    if row["court"] == apex:
        weight += 0.2
    weight += 0.05 * math.log1p(citing.get(row["doc_id"], 0))
    return weight


def _citing(corpus: Corpus, doc_ids: set[str]) -> dict[str, int]:
    if not doc_ids:
        return {}
    listed = list(doc_ids)
    return dict(
        corpus.sql(
            "select case_id, citing from citing_counts where list_contains(?, case_id)", [listed]
        )
    )


def _group(corpus: Corpus, hits: list[Hit], limit: int) -> list[tuple[dict, list[Hit]]]:
    """Group hits by document, best first, applying the priors."""
    citing = _citing(corpus, {h.row["doc_id"] for h in hits if h.row["kind"] == "case"})
    for hit in hits:
        hit.score *= _prior(hit.row, citing, corpus.profile.apex)
    by_doc: dict[str, list[Hit]] = {}
    for hit in sorted(hits, key=lambda h: h.score, reverse=True):
        # Provisions are their own documents: two sections of one Act are two results.
        key = hit.row["id"] if hit.row["kind"] == "provision" else hit.row["doc_id"]
        by_doc.setdefault(key, []).append(hit)
    groups = list(by_doc.values())[:limit]
    return [
        ({"citing": citing.get(g[0].row["doc_id"])}, g[:SEARCH_SNIPPETS_PER_CASE]) for g in groups
    ]


def _who(corpus: Corpus, row: dict) -> str:
    if not row["segment_authors"]:
        return ""
    label = corpus.reasons_words(row["doc_id"], row["segment_authors"], row["segment_kind"])
    return f" [{row['segment_authors']}{', ' + label if label else ''}]"


def _unit_label(corpus: Corpus, row: dict) -> str:
    if row["kind"] == "provision":
        return f"{'r' if names_rules(row['doc_id']) else 's'} {row['section']}"
    if row["kind"] == "commentary":
        return f"passage {row['number']}"
    return corpus.profile.unit(row["unit"], row["number"])


def format_results(corpus: Corpus, groups, terms: list[str], how: str) -> str:
    """The results as the model reads them."""
    if not groups:
        return f"No results ({how})."
    lines = [f"{len(groups)} result(s), {how}:"]
    for n, (meta, hits) in enumerate(groups, 1):
        first = hits[0].row
        if first["kind"] == "commentary":
            head = (
                f"{n}. {first['title']}, {first['doc_id']} (commentary: explains, is not authority)"
            )
        elif first["kind"] == "provision":
            note = f" ({first['note']})" if first["note"] else ""
            name = (
                first["title"]
                if first["title"] == first["doc_id"]
                else (f"{first['title']}, {first['doc_id']}")
            )
            head = f"{n}. {name}, {_unit_label(corpus, first)}{note}"
        else:
            head = f"{n}. {first['title']}, {first['doc_id']} ({first['court']} {first['year']})"
            if meta["citing"]:
                head += f" · cited by {meta['citing']}"
        if first["syllabus"]:
            head += f" · {corpus.profile.spine.upper()} READING"
        lines.append(head)
        for hit in hits:
            row = hit.row
            unchecked = (
                " (our numbering: cite the case, not this passage)"
                if row["unit"] == "block" and row["kind"] == "case"
                else ""
            )
            who = _who(corpus, row)
            lines.append(
                f"   {_unit_label(corpus, row)}{who}{unchecked}: {snippet(row['text'], terms)}"
            )
    return "\n".join(lines)


def keyword_groups(
    corpus: Corpus, query: str, filters: Filters, within: int = 0, limit: int = SEARCH_MAX_CASES
) -> list[tuple[dict, list[Hit]]]:
    """Keyword search's ranked documents, before formatting (the retrieval eval reads these)."""
    rows = (
        corpus.search_table.search(_fts_query(query, within))
        .where(filters.where(), prefilter=True)
        .select(_COLUMNS)
        .limit(SEARCH_CANDIDATES)
        .to_list()
    )
    top = max((r["_score"] for r in rows), default=1.0) or 1.0
    return _group(corpus, [Hit(r, r["_score"] / top) for r in rows], min(limit, SEARCH_MAX_CASES))


def semantic_groups(
    corpus: Corpus,
    query: str,
    filters: Filters,
    limit: int = SEARCH_MAX_CASES,
    *,
    embed_query: Callable[[str], tuple[list[float], float]],
    rerank: Callable[[str, list[str]], tuple[list[float], float]],
) -> tuple[list[tuple[dict, list[Hit]]], float]:
    """Retrieve and rerank with consumer-supplied models; return (documents, cost in USD)."""
    vector, embed_cost = embed_query(query)
    rows = (
        corpus.search_table.search(vector)
        .where(filters.where(), prefilter=True)
        .nprobes(VECTOR_NPROBES)
        .refine_factor(VECTOR_REFINE_FACTOR)
        .select(_COLUMNS)
        .limit(SEARCH_CANDIDATES)
        .to_list()
    )
    if not rows:
        return [], embed_cost
    documents = [f"{r['title']}: {r['text'][:1500]}" for r in rows]
    scores, rerank_cost = rerank(query, documents)
    hits = [Hit(r, s) for r, s in zip(rows, scores, strict=True)]
    return _group(corpus, hits, min(limit, SEARCH_MAX_CASES)), embed_cost + rerank_cost


def keyword_search(
    corpus: Corpus, query: str, filters: Filters, within: int = 0, limit: int = SEARCH_MAX_CASES
) -> str:
    groups = keyword_groups(corpus, query, filters, within, limit)
    return format_results(corpus, groups, _highlight_terms(query), "keyword (BM25)")


def semantic_search(
    corpus: Corpus,
    query: str,
    filters: Filters,
    limit: int = SEARCH_MAX_CASES,
    *,
    embed_query: Callable[[str], tuple[list[float], float]],
    rerank: Callable[[str, list[str]], tuple[list[float], float]],
) -> tuple[str, float]:
    """Semantic search as the model reads it. Returns (text, cost)."""
    groups, cost = semantic_groups(
        corpus, query, filters, limit, embed_query=embed_query, rerank=rerank
    )
    terms = [w.lower() for w in query.split() if len(w) > 4]
    return format_results(corpus, groups, terms, "semantic (embeddings, reranked)"), cost
