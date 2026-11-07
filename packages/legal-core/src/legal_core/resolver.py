"""
Resolving parsed case citations to the cases we hold.

A case is known by several citations: its neutral citation, its SCR citation,
and a scatter of other reports (DLR, CCC, OR...). A2AJ records only the first
two, so on its own it cannot tell that "26 DLR (4th) 200" is *R v Oakes*. The
corpus can: judgments routinely cite a case by all of its reports at once
("R. v. Oakes, [1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200"), so a report that
keeps appearing beside a citation we can resolve is learned as another name for
that case. That is `learn_parallel_citations` (research/0004 §4).
"""

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from legal_core.citations import CaseCitation, clean_text, find_case_citations

logger = logging.getLogger(__name__)

# A parallel citation is only learned from repeated, one-sided evidence: at least
# this many runs, and at least this share of them pointing at the same case.
MIN_PARALLEL_VOTES = 2
MIN_PARALLEL_SHARE = 0.8
# Citations that name one decision by its own identity, unlike a report, which
# may be any of several cases' parallel citations: neutral citations (Canada's
# "2011 SCC 5", and bracketed ones such as "[2011] NZCA 531") and file numbers.
_IDENTIFYING = {"neutral", "foreign", "file"}

# Two citations belong to one run when nothing but commas and spaces (or a
# "(CanLII)" tag) separates them. A semicolon or any words between them means a
# different case, so they are not a run.
_RUN_GAP = re.compile(r"^[\s,]*(?:\(CanLII\))?[\s,]*$")


@dataclass(frozen=True)
class KnownCase:
    """A case we hold: its id (A2AJ `citation_en`) and every citation string recorded for it."""

    case_id: str
    citations: tuple[str, ...]


class CaseIndex:
    """Maps canonical citation keys to case ids."""

    def __init__(self, cases: Iterable[KnownCase]):
        self._by_key: dict[str, str] = {}
        ambiguous: set[str] = set()
        for case in cases:
            for citation in case.citations:
                for found in find_case_citations(clean_text(citation)):
                    existing = self._by_key.get(found.key)
                    if existing and existing != case.case_id:
                        ambiguous.add(found.key)
                    self._by_key[found.key] = case.case_id
        # A key recorded for two different cases resolves to neither: a guess
        # here would be a false edge in the graph.
        for key in ambiguous:
            del self._by_key[key]
        self.learned = 0
        logger.info(
            "Case index: %d keys, %d ambiguous keys dropped", len(self._by_key), len(ambiguous)
        )

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> "CaseIndex":
        """
        Restore an index from its (key, case id) pairs, as the ingest job publishes it.

        Learning parallel citations reads every paragraph of the corpus, so the
        app does not repeat it: it loads the finished index from the snapshot.
        """
        index = cls([])
        index._by_key = dict(pairs)
        return index

    def pairs(self) -> list[tuple[str, str]]:
        """Every (canonical key, case id) pair, learned parallel citations included."""
        return list(self._by_key.items())

    def resolve(self, key: str) -> str | None:
        """The case id for a canonical key, or None if we do not hold it."""
        return self._by_key.get(key)

    def __len__(self) -> int:
        return len(self._by_key)

    def learn_parallel_citations(self, texts: Iterable[str]) -> int:
        """
        Learn report citations that the corpus shows are other names for known cases.

        Scans `texts` for runs of adjacent citations. In a run that resolves to
        exactly one known case, every unresolved key gets a vote for that case.
        A run that resolves to no case but names its decision by its own identity
        (a neutral citation or a file number) is about a decision we do not hold,
        so its unresolved keys get a vote for no case. Without those votes, a
        couple of typos ("[2011] NZCA 53, (2011) 25 CRNZ 446" for 531, which is
        not held) were the only evidence and taught a report to the wrong case
        (debug/2026-10-03-nz-identity-and-parallels.md). A key is learned when it
        has enough votes and they agree. Returns how many keys were learned.
        """
        votes: dict[str, Counter[str | None]] = defaultdict(Counter)
        for text in texts:
            for run in citation_runs(clean_text(text)):
                resolved = {self.resolve(c.key) for c in run} - {None}
                if len(resolved) == 1:
                    [case_id] = resolved
                elif not resolved and any(c.kind in _IDENTIFYING for c in run):
                    case_id = None
                else:
                    continue
                for citation in run:
                    if self.resolve(citation.key) is None:
                        votes[citation.key][case_id] += 1
        learned = 0
        for key, counter in votes.items():
            case_id, top = counter.most_common(1)[0]
            if case_id is None:
                continue
            if top >= MIN_PARALLEL_VOTES and top / sum(counter.values()) >= MIN_PARALLEL_SHARE:
                self._by_key[key] = case_id
                learned += 1
        self.learned += learned
        logger.info("Learned %d parallel citations from %d candidate keys", learned, len(votes))
        return learned


def citation_runs(text: str) -> list[list[CaseCitation]]:
    """
    Group the citations in `text` into runs of adjacent citations of (presumably) one case.

    Only runs of two or more are returned, since a lone citation teaches nothing
    about parallels. The pinpoint belongs to the citation it follows, so a run
    is broken by "at para. 3" only if words other than the pinpoint intervene.
    """
    runs: list[list[CaseCitation]] = []
    current: list[CaseCitation] = []
    for citation in find_case_citations(text):
        if current and _RUN_GAP.match(text[current[-1].end : citation.start]):
            current.append(citation)
            continue
        if len(current) > 1:
            runs.append(current)
        current = [citation]
    if len(current) > 1:
        runs.append(current)
    return runs
