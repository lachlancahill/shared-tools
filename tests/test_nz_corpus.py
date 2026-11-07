"""NZ-only and mixed-corpus checks using invented NZ text, not published judgments."""

import pytest
from conftest import NZ_CASE, OAKES
from legal_core.nz import HIGH_COURT_RULES
from legal_corpus import reader, search, verify


def test_nz_can_be_the_primary_corpus_and_short_forms_keep_their_pinpoints(nz_corpus):
    read = reader.read(nz_corpus, f"{NZ_CASE} at [2]")
    assert "*[2]" in read.text and "invented judgment" in read.text
    assert f"{NZ_CASE}#2" in read.unit_ids
    answer = f"Example v Sample {NZ_CASE} at [2]. Later, Example at [3]."
    checked = verify.verify(nz_corpus, answer, set(read.unit_ids))
    assert len(checked) == 2
    assert all(c.status == "verified" and not c.badges for c in checked)


@pytest.mark.parametrize(
    "answer",
    [
        "The rule is r 138 of the High Court Rules.",
        "See High Court Rules 2016, r 138.",
        "See HCR r 138.",
        "See s 138 of the High Court Rules.",
    ],
)
def test_a_named_rule_the_instrument_cannot_have_is_flagged_not_missed(nz_corpus, answer):
    """A model repeating old numbering must see a warning, not a clean answer."""
    checked = verify.verify(nz_corpus, answer, set())
    assert [(c.status, c.badges) for c in checked] == [("unverified", ["not in the corpus"])]


def test_an_old_rule_number_tells_the_model_it_is_not_held_rather_than_just_missing(nz_corpus):
    old = reader.read(nz_corpus, "HCR r 138").text
    assert "No r 138 of" in old and "earlier High Court Rules are not held" in old
    # A dotted number could be a real rule we lack, so it gets no such explanation.
    assert "not held" not in reader.read(nz_corpus, "HCR r 8.99").text


def test_mixed_corpora_remain_distinct_and_revoked_rules_are_badged(corpus, nz_corpus):
    answer = f"Oakes {OAKES} at para 69. Example {NZ_CASE} at [2]. HCR r 8.7."
    checked = verify.verify(corpus, answer, {f"{OAKES}#69", f"{NZ_CASE}#2"}, nz=nz_corpus)
    assert [c.status for c in checked] == ["verified"] * 3
    assert checked[0].link.startswith("/cases/")
    assert checked[1].link.startswith("/nz/cases/")
    assert checked[2].target == f"{HIGH_COURT_RULES} s 8.7"
    assert "revoked" in checked[2].badges
    assert "revoked, on 1 January 2026" in reader.read(nz_corpus, "r 8.7").text
    results = search.keyword_search(nz_corpus, "discovery", search.Filters(kind="legislation"))
    assert "r 8.4" in results


def test_consumer_loader_is_only_used_when_nz_law_is_mentioned(nz_corpus):
    calls = []

    def load():
        calls.append(True)
        return nz_corpus

    assert verify.nz_needed([f"Oakes {OAKES} at para 69."], load) is None
    assert calls == []
    assert verify.nz_needed([f"See {NZ_CASE} at [2]."], load) is nz_corpus
    assert calls == [True]
