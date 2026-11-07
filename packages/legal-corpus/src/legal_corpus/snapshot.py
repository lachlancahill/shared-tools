"""
The published corpus, as the app holds it (research/0003, 0005).

At start-up the app reads `current.json`, loads that snapshot's graph tables into
an in-memory DuckDB database, and opens its LanceDB search table on GCS (queried in
place, never downloaded: research/0012 measured 108–212 ms medians). The citation
index and the statute names are restored too, so the answer checker resolves a
citation exactly as the ingest job did.

Paragraph *text* is never loaded into memory; it lives in the search table
(research/0003's consequence). What is loaded is metadata and edges, tens of MB.

DuckDB connections are not safe to share between threads, and the app serves a
turn per thread, so every query runs on a cursor of its own (`Corpus.sql`).
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field

import duckdb
import lancedb
import pyarrow.fs as pafs
import pyarrow.parquet as pq
from legal_core.citations import StatuteNames, base_section, normalise_case_name
from legal_core.nz import year_less_names
from legal_core.resolver import CaseIndex

from legal_corpus.profile import CANADA, Profile
from legal_corpus.reasons import classify, describe

logger = logging.getLogger(__name__)

# Each graph table and the columns the app needs from it. `cases.parquet` also
# carries each decision's headnote text, which is left on GCS.
TABLES = {
    "cases": [
        "case_id",
        "dataset",
        "tier",
        "name",
        "decision_date",
        "citations",
        "url",
        "unit",
        "unit_count",
        "judges",
        "subjects",
        "appeal_from",
        "segments",
        "read_by_ocr",
    ],
    "cites": [
        "citing_case",
        "citing_unit",
        "key",
        "cited_case",
        "pin_para",
        "pin_para_end",
        "pin_page",
    ],
    "citation_keys": ["key", "case_id"],
    "treatments": ["citing_case", "cited_case", "treatment", "judge"],
    "llm_treatments": ["citing_case", "cited_case", "treatment", "paragraph"],
    "interprets": ["citing_case", "citing_unit", "statute", "section"],
    "statutes": ["statute_id", "title", "dataset", "tier", "url", "section_count"],
    "definitions": ["statute_id", "section", "scope", "term", "text"],
    "briefs": ["case_id", "brief", "reviewed", "prompt_version"],
    "roles": ["case_id", "first", "last", "role"],
    "tests": ["case_id", "slug", "name", "relation", "statement", "steps"],
}
SEARCH_TABLE = "units"


@dataclass
class SyllabusIndex:
    """The syllabi, plus which topics list each case and provision as a reading."""

    subjects: dict[str, dict]
    topics_for_case: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    topics_for_provision: dict[tuple[str, str], list[tuple[str, str, str]]] = field(
        default_factory=dict
    )


class Corpus:
    """
    One loaded snapshot: graph tables in DuckDB, the search table on GCS.

    `profile` says which corpus: Canada's, or New Zealand's (research/0024), each
    with its own snapshot pointer, short statute names and pinpoint style.
    """

    def __init__(self, profile: Profile = CANADA):
        started = time.monotonic()
        self.profile = profile
        corpus_uri = profile.corpus_uri
        filesystem, root = pafs.FileSystem.from_uri(corpus_uri)
        with filesystem.open_input_stream(f"{root}/current.json") as f:
            pointer = json.loads(f.read())
        self.snapshot = pointer["snapshot"]
        self.snapshot_uri = f"{corpus_uri}/{self.snapshot}"
        snapshot_root = f"{root}/{self.snapshot}"

        self._con = duckdb.connect()
        for name, columns in TABLES.items():
            table = pq.read_table(
                f"{snapshot_root}/{name}.parquet", filesystem=filesystem, columns=columns
            )
            if name == "cites":
                # Only resolved edges are ever queried; the rest measure the resolver.
                table = table.filter(table.column("cited_case").is_valid())
            self._con.register(f"_{name}", table)
            self._con.execute(f"create table {name} as select * from _{name}")
            self._con.unregister(f"_{name}")
        self._con.execute(
            "create table citing_counts as select cited_case as case_id, "
            "count(distinct citing_case) as citing from cites group by 1"
        )
        with filesystem.open_input_stream(f"{snapshot_root}/manifest.json") as f:
            self.manifest = json.loads(f.read())
        with filesystem.open_input_stream(f"{snapshot_root}/syllabus.json") as f:
            self.syllabus = _syllabus_index(json.loads(f.read()))

        # Everything is loaded, so the database is sealed: the research skill's
        # read-only SQL tool (`graph_sql`) runs against this connection, and with
        # external access off no query can read a file or reach the network.
        self._con.execute("set enable_external_access = false")
        self._con.execute("set lock_configuration = true")

        self.case_index = CaseIndex.from_pairs(self.sql("select key, case_id from citation_keys"))
        statutes = self.sql("select statute_id, title from statutes")
        if profile.year_less_names:
            in_force = [t for (t,) in self.sql("select title from statutes where tier = 'A'")]
            statutes += year_less_names(in_force)
        self.statute_names = StatuteNames(statutes, built_in=profile.statute_names)
        self.names: dict[str, list[str]] = {}
        for case_id, name in self.sql(
            "select case_id, name from cases where list_contains(?, tier)",
            [list(profile.named_tiers)],
        ):
            self.names.setdefault(normalise_case_name(name), []).append(case_id)

        self._reasons: dict[str, tuple[dict[str, str], list[str]]] = {}
        self._search_uri = f"{self.snapshot_uri}/search"
        self._search = None
        self._search_lock = threading.Lock()
        logger.info("Corpus %s loaded in %.1f s", self.snapshot, time.monotonic() - started)

    # --- Access ----------------------------------------------------------------

    def sql(self, query: str, params: list | None = None) -> list[tuple]:
        """Run a query on this thread's own cursor and return every row."""
        return self._con.cursor().execute(query, params or []).fetchall()

    def reasons(self, case_id: str) -> tuple[dict[str, tuple[str, int]], list[str]]:
        """
        A case's reasons, by authors line: their kind corrected for size (a
        "majority" of three judges is a plurality, `reasons.classify`) and how many
        signed them; and the case's bench.
        Cached: the answer cannot change within a snapshot.
        """
        if case_id not in self._reasons:
            rows = self.sql_dicts("select segments, judges from cases where case_id = ?", [case_id])
            segments, bench = (
                (rows[0]["segments"] or [], rows[0]["judges"] or []) if rows else ([], [])
            )
            self._reasons[case_id] = (classify(segments, bench), bench)
        return self._reasons[case_id]

    def reasons_kind(self, case_id: str, authors: str | None, kind: str | None) -> str:
        """One passage's kind: its reasons' corrected kind, else the stored label."""
        if not authors:
            return kind or ""
        return self.reasons(case_id)[0].get(authors, (kind or "", 0))[0]

    def reasons_words(self, case_id: str, authors: str | None, kind: str | None) -> str:
        """How a passage's reasons are described: "plurality: 3 of 9 judges, no majority"."""
        kinds, bench = self.reasons(case_id)
        corrected, signed = kinds.get(authors or "", (kind or "", 0))
        return describe(corrected, signed, bench)

    def sql_dicts(self, query: str, params: list | None = None) -> list[dict]:
        cursor = self._con.cursor().execute(query, params or [])
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    @property
    def search_table(self):
        """The LanceDB table, opened on first use (74 ms, research/0012)."""
        with self._search_lock:
            if self._search is None:
                self._search = lancedb.connect(self._search_uri).open_table(SEARCH_TABLE)
            return self._search

    def case(self, case_id: str) -> dict | None:
        rows = self.sql_dicts(
            "select c.*, coalesce(n.citing, 0) as citing from cases c "
            "left join citing_counts n using (case_id) where c.case_id = ?",
            [case_id],
        )
        return rows[0] if rows else None

    def units(self, case_id: str, numbers: list[int]) -> list[dict]:
        """Units of one case by number, in order, from the search table."""
        if not numbers:
            return []
        listed = ", ".join(str(int(n)) for n in numbers)
        return (
            self.search_table.search()
            .where(f"doc_id = {_quote(case_id)} and kind = 'case' and number in ({listed})")
            .select(_UNIT_COLUMNS)
            .limit(len(numbers))
            .to_list()
        )

    def units_by_id(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        listed = ", ".join(_quote(i) for i in ids)
        rows = (
            self.search_table.search()
            .where(f"id in ({listed})")
            .select(_UNIT_COLUMNS)
            .limit(len(ids))
            .to_list()
        )
        return {r["id"]: r for r in rows}

    def provision(self, statute_id: str, section: str) -> dict | None:
        rows = (
            self.search_table.search()
            .where(f"doc_id = {_quote(statute_id)} and section = {_quote(section)}")
            .select(_UNIT_COLUMNS)
            .limit(1)
            .to_list()
        )
        return rows[0] if rows else None

    def statute(self, statute_id: str) -> dict | None:
        rows = self.sql_dicts("select * from statutes where statute_id = ?", [statute_id])
        return rows[0] if rows else None


_UNIT_COLUMNS = [
    "id",
    "kind",
    "doc_id",
    "number",
    "section",
    "unit",
    "heading",
    "note",
    "page",
    "segment_kind",
    "segment_authors",
    "court",
    "year",
    "tier",
    "title",
    "syllabus",
    "text",
]


def _quote(value: str) -> str:
    """A string literal for a Lance filter. Values here are ids, never free text."""
    return "'" + value.replace("'", "''") + "'"


def _syllabus_index(subjects: list[dict]) -> SyllabusIndex:
    index = SyllabusIndex({s["subject"]: s for s in subjects})
    for subject in subjects:
        for topic in subject["topics"]:
            where = (subject["subject"], topic["id"], topic["title"])
            for reading in topic["readings"]:
                if reading["kind"] == "case" and reading.get("case_id"):
                    index.topics_for_case.setdefault(reading["case_id"], []).append(where)
                elif reading["kind"] == "provision":
                    key = (reading["statute"], base_section(reading["section"]))
                    index.topics_for_provision.setdefault(key, []).append(where)
    return index
