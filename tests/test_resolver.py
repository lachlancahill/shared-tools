"""Resolving citations to cases, and learning parallel citations from the corpus."""

from legal_core.resolver import CaseIndex, KnownCase, citation_runs

OAKES = KnownCase("[1986] 1 SCR 103", ("[1986] 1 SCR 103",))
VAVILOV = KnownCase("2019 SCC 65", ("2019 SCC 65", "[2019] 4 SCR 653"))
MORGENTALER = KnownCase("[1993] 3 SCR 463", ("[1993] 3 SCR 463",))


def test_resolves_every_recorded_citation():
    index = CaseIndex([OAKES, VAVILOV])
    assert index.resolve("2019 SCC 65") == "2019 SCC 65"
    assert index.resolve("[2019] 4 SCR 653") == "2019 SCC 65"
    assert index.resolve("[1986] 1 SCR 103") == "[1986] 1 SCR 103"
    assert index.resolve("26 DLR (4th) 200") is None


def test_a_key_claimed_by_two_cases_resolves_to_neither():
    clash = KnownCase("C29360", ("[1986] 1 SCR 103",))
    index = CaseIndex([OAKES, clash])
    assert index.resolve("[1986] 1 SCR 103") is None


def test_runs_are_broken_by_words_and_semicolons():
    text = (
        "R. v. Oakes, [1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200; "
        "R. v. Morgentaler, [1993] 3 S.C.R. 463, 107 D.L.R. (4th) 537, and see 2019 SCC 65"
    )
    runs = [[c.key for c in run] for run in citation_runs(text)]
    assert runs == [
        ["[1986] 1 SCR 103", "26 DLR (4th) 200"],
        ["[1993] 3 SCR 463", "107 DLR (4th) 537"],
    ]


def test_parallel_citation_learned_from_repeated_agreement():
    index = CaseIndex([OAKES, MORGENTALER])
    texts = [
        "as held in R. v. Oakes, [1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200, the test",
        "Oakes, [1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200, at p. 225",
    ]
    assert index.learn_parallel_citations(texts) == 1
    assert index.resolve("26 DLR (4th) 200") == "[1986] 1 SCR 103"


def test_a_single_sighting_is_not_enough():
    index = CaseIndex([OAKES])
    index.learn_parallel_citations(["Oakes, [1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200"])
    assert index.resolve("26 DLR (4th) 200") is None


def test_conflicting_evidence_is_not_learned():
    index = CaseIndex([OAKES, MORGENTALER])
    texts = [
        "[1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200",
        "[1986] 1 S.C.R. 103, 26 D.L.R. (4th) 200",
        "[1993] 3 S.C.R. 463, 26 D.L.R. (4th) 200",
        "[1993] 3 S.C.R. 463, 26 D.L.R. (4th) 200",
    ]
    index.learn_parallel_citations(texts)
    assert index.resolve("26 DLR (4th) 200") is None


def test_a_report_of_an_unheld_decision_is_not_learned_from_typos():
    # Churchward v R [2011] NZCA 531, (2011) 25 CRNZ 446 is not held; two judgments
    # mistyped it as [2011] NZCA 53, which is held, and those were the only votes.
    held = KnownCase("[2011] NZCA 53", ("[2011] NZCA 53",))
    index = CaseIndex([held])
    texts = ["Churchward v R [2011] NZCA 53, (2011) 25 CRNZ 446 at [77]"] * 2
    texts += ["Churchward v R [2011] NZCA 531, (2011) 25 CRNZ 446 at [77]"] * 4
    index.learn_parallel_citations(texts)
    assert index.resolve("25 CRNZ 446") is None


def test_a_mistyped_neutral_beside_a_held_report_is_still_learned():
    # A run that resolves to one held case still votes for it: Canada's corpus
    # learns typos such as "2003 SCC 445" for 2003 SCC 45 this way.
    index = CaseIndex([VAVILOV])
    index.learn_parallel_citations(["Vavilov, 2019 SCC 655, [2019] 4 S.C.R. 653"] * 2)
    assert index.resolve("2019 SCC 655") == "2019 SCC 65"
