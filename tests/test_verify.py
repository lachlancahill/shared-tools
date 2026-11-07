"""The answer checker: every citation checked, and the context badges it adds."""

from conftest import CODE, OAKES
from legal_corpus import verify


def _check(corpus, answer, read=()):
    return {c.text: c for c in verify.verify(corpus, answer, set(read))}


def test_a_read_pinpoint_verifies_cleanly(corpus):
    found = _check(
        corpus,
        "The objective must be pressing: R v Oakes, [1986] 1 SCR 103 at para 69.",
        [f"{OAKES}#69"],
    )
    citation = found["[1986] 1 SCR 103 at para 69"]
    assert citation.status == "verified" and citation.badges == []
    assert citation.link.endswith("#u69")


def test_an_unread_pinpoint_is_flagged(corpus):
    found = _check(corpus, "See [1986] 1 SCR 103 at para 70.")
    assert "not read in context" in found["[1986] 1 SCR 103 at para 70"].badges


def test_a_pinpoint_into_a_dissent_is_flagged(corpus):
    found = _check(corpus, "See [1986] 1 SCR 103 at para 72.", [f"{OAKES}#72"])
    assert "dissent" in found["[1986] 1 SCR 103 at para 72"].badges


def test_an_invented_case_and_a_missing_paragraph_are_unverified(corpus):
    found = _check(corpus, "See 2031 SCC 7, and [1986] 1 SCR 103 at para 400.")
    assert found["2031 SCC 7"].status == "unverified"
    assert "pinpoint does not exist" in found["[1986] 1 SCR 103 at para 400"].badges


def test_quotes_are_checked_at_the_pinpoint(corpus):
    good = _check(
        corpus,
        '"must be of sufficient importance to warrant overriding a '
        'constitutionally protected right" ([1986] 1 SCR 103 at para 69).',
        [f"{OAKES}#69"],
    )
    bad = _check(
        corpus,
        '"a law is valid whenever Parliament says it is so" ([1986] 1 SCR 103 at para 69).',
        [f"{OAKES}#69"],
    )
    assert "quote not found at the pinpoint" not in good["[1986] 1 SCR 103 at para 69"].badges
    assert "quote not found at the pinpoint" in bad["[1986] 1 SCR 103 at para 69"].badges


def test_a_quote_is_looked_for_across_the_whole_pinpointed_range(corpus):
    # The quote is in para 72, the range's end: checking only around para 69 (68–70)
    # once marked a quote "not found" that was in the range (2021 ONCA 371, paras 1–3).
    oakes = [f"{OAKES}#{n}" for n in range(69, 73)]
    found = _check(
        corpus, '"I would decide this appeal differently" ([1986] 1 SCR 103 at paras 69–72).', oakes
    )
    short = _check(
        corpus,
        'R v Oakes, [1986] 1 SCR 103. Later: "I would decide this appeal differently" '
        "(*Oakes*, at paras 69–72).",
        oakes,
    )
    assert "quote not found at the pinpoint" not in found["[1986] 1 SCR 103 at paras 69–72"].badges
    assert "quote not found at the pinpoint" not in short["*Oakes*, at paras 69–72"].badges


def test_a_range_end_that_does_not_exist_is_flagged(corpus):
    found = _check(corpus, "See [1986] 1 SCR 103 at paras 69–400.", [f"{OAKES}#69"])
    assert "pinpoint does not exist" in found["[1986] 1 SCR 103 at paras 69–400"].badges


def test_short_forms_resolve_against_cases_cited_in_full(corpus):
    found = _check(
        corpus, "R v Oakes, [1986] 1 SCR 103 at para 69, and later (*Oakes*, at para 70)."
    )
    assert found["*Oakes*, at para 70"].target == OAKES


def test_provisions_are_checked_and_linked(corpus):
    found = _check(corpus, "Assault is defined in s. 265 of the Criminal Code.")
    citation = next(iter(found.values()))
    assert citation.kind == "provision" and citation.status == "verified"
    assert "not read in context" in citation.badges


def test_offsets_survive_odd_spaces_in_the_original():
    answer = "See Oakes , [1986] 1 SCR 103 at para 69 now."
    cleaned = "See Oakes, [1986] 1 SCR 103 at para 69 now."
    mapping = verify._offset_map(answer, cleaned)
    start = cleaned.index("[1986]")
    assert answer[mapping[start] :].startswith("[1986]")


def test_annotation_links_each_citation_with_its_marks(corpus):
    answer = "See 2031 SCC 7."
    html = verify.annotate(answer, verify.verify(corpus, answer, set()))
    assert 'class="cite cite-unverified"' in html and "not in the corpus" in html


def test_bare_pinpoints_are_checked_against_the_case_named_before_them(corpus):
    answer = "In R v Oakes, [1986] 1 SCR 103, the court set the test (paras 69–70), (para 400)."
    found = _check(corpus, answer, [f"{OAKES}#69", f"{OAKES}#70"])
    assert found["paras 69–70"].status == "verified" and found["paras 69–70"].badges == []
    assert "pinpoint does not exist" in found["para 400"].badges
    # The case is pinpointed after all, so its bare citation carries no "no pinpoint".
    assert "no pinpoint" not in found["[1986] 1 SCR 103"].badges


# The shapes below are from a real answer (research/debug/2026-10-01-checker-missed-citations.md),
# where each went unchecked and showed no mark at all.


def test_markdown_emphasis_does_not_hide_a_provision(corpus):
    answer = "Assault is defined (*Criminal Code*, s 265), and see **Criminal Code** s 266."
    found = _check(corpus, answer)
    # A name before the section is not part of the span: "s 265" carries the mark.
    assert found["s 265"].status == "verified" and found["s 265"].target
    assert found["s 266"].status == "verified" and found["s 266"].target


def test_a_link_never_cuts_an_emphasis_marker_in_half(corpus):
    answer = (
        "R v Oakes, [1986] 1 SCR 103 at para 69. Later: *Oakes* at para 70, "
        "*The Queen and Oakes* at para 71, and **Criminal Code s 265**: assault."
    )
    found = _check(corpus, answer)
    assert "*Oakes* at para 70" in found
    assert "*The Queen and Oakes* at para 71" in found  # the short form starts at "Oakes"
    assert "s 265" in found  # inside the bold, not "s 265**"


def test_a_short_form_can_pinpoint_a_range(corpus):
    answer = (
        "R v Oakes, [1986] 1 SCR 103. The test: *Oakes* at paras 69–70, "
        "and *Oakes* at paras 70–400."
    )
    found = _check(corpus, answer, [f"{OAKES}#69", f"{OAKES}#70"])
    assert found["*Oakes* at paras 69–70"].badges == []
    assert "pinpoint does not exist" in found["*Oakes* at paras 70–400"].badges


def test_a_bare_pinpoint_goes_to_the_case_last_named_on_its_line(corpus):
    # Two cases are cited; the mention of *Oakes* by name on the second line decides it.
    answer = (
        "R v Oakes, [1986] 1 SCR 103, and R v Moral, 2020 SCC 99 at para 1.\n\n"
        "In *Oakes*, the objective must be pressing: para 69. "
        "The Chief Justice in *Oakes* (majority reasons, at para 70) went on."
    )
    found = _check(corpus, answer)
    assert found["para 69"].target == OAKES and found["para 69"].status == "verified"
    assert found["at para 70"].target == OAKES


def test_initials_are_not_a_short_name():
    assert verify._short_name("Re B.C. Motor Vehicle Act") == "Motor"
    assert verify._short_name("R. v. Oakes") == "Oakes"


# The shapes below are from a follow-up turn
# (research/debug/2026-10-01-conversation-review-topic-5.md), whose pinpoints were all
# credited to the one case it cited in full, each with a tick.


def test_a_follow_up_calls_earlier_answers_cases_by_short_name(corpus):
    answer = "- **Oakes** paras 69–70 — the objective (para 69). Confirmed."
    alone = _check(corpus, answer, [f"{OAKES}#69", f"{OAKES}#70"])
    assert alone == {}  # nothing in this answer says which case: left unmarked
    found = {
        c.text: c for c in verify.verify(corpus, answer, {f"{OAKES}#69", f"{OAKES}#70"}, [OAKES])
    }
    assert found["**Oakes** paras 69–70"].target == OAKES
    assert found["para 69"].target == OAKES and found["para 69"].badges == []


def test_a_bare_pinpoint_is_never_credited_to_the_only_case_by_default(corpus):
    answer = "- Moral, 2020 SCC 99 at para 1 applies it.\n- Charkaoui settles it (para 18)."
    found = _check(corpus, answer)
    assert "para 18" not in found and "(para 18)" not in found


def test_a_short_name_two_cases_share_is_dropped():
    class Cases:
        def case(self, case_id):
            return {
                "name": {"a": "Singh v. Canada", "b": "R. v. Singh", "c": "R. v. Oakes"}[case_id]
            }

    assert verify._short_names(Cases(), ["a", "b"], ["c"]) == {"Oakes": "c"}
    # This answer's own case wins over an earlier one, and an ambiguous name stays dropped.
    assert verify._short_names(Cases(), ["a"], ["b"]) == {"Singh": "a"}
    assert verify._short_names(Cases(), ["a", "b"], ["c", "b"]) == {"Oakes": "c"}


def test_a_conversation_is_checked_answer_by_answer(corpus):
    messages = [
        {"role": "user", "content": "Teach me Oakes."},
        {
            "role": "assistant",
            "content": "R v Oakes, [1986] 1 SCR 103 at para 69.",
            "read_ids": [f"{OAKES}#69"],
        },
        {"role": "user", "content": "Check it."},
        {"role": "assistant", "content": "*Oakes* at para 69, and *Oakes* at para 70."},
        {"role": "assistant", "content": "Cut short: *Oakes* at para", "stopped": True},
    ]
    _, first, _, second, stopped = (
        {c.text: c for c in checked} if checked is not None else None
        for checked in verify.check_conversation(corpus, messages)
    )
    assert first["[1986] 1 SCR 103 at para 69"].badges == []
    # Read in the first turn, so still read when the second relies on it.
    assert second["*Oakes* at para 69"].badges == []
    assert second["*Oakes* at para 70"].badges == ["not read in context"]
    assert stopped is None


# Legislation: sections written without their statute, as legal prose writes them.


def _provisions(corpus, answer):
    return [
        (c.text, c.target) for c in verify.verify(corpus, answer, set()) if c.kind == "provision"
    ]


def test_the_bill_of_rights_is_linked_by_its_short_name(corpus):
    assert _provisions(corpus, "| Charter s 7 | Bill of Rights s 2(e) |") == [
        ("s 7", "Constitution Act, 1982 s 7"),
        ("s 2(e)", "SC 1960, c 44 s 2"),
    ]


def test_a_bare_section_takes_the_statute_named_earlier_in_its_sentence(corpus):
    answer = (
        "**Text** (*Canadian Bill of Rights*, SC 1960, c 44): s 1(a) protects property; "
        "s 2(e) provides a fair hearing."
    )
    assert _provisions(corpus, answer) == [
        ("s 1(a)", "SC 1960, c 44 s 1"),
        ("s 2(e)", "SC 1960, c 44 s 2"),
    ]


def test_a_section_the_answer_pairs_with_a_statute_keeps_it(corpus):
    answer = (
        "The gate is Charter s 7.\n\n"
        "The Bill of Rights has its own triggers; it does not piggyback on s 7."
    )
    assert [target for _, target in _provisions(corpus, answer)] == [
        "Constitution Act, 1982 s 7"
    ] * 2


def test_a_bare_section_nothing_settles_is_left_unmarked(corpus):
    # No statute in the sentence and no pairing; and a guess the statute cannot hold.
    answer = (
        "| Justification | s 1 (and s 33) |\n"
        "The Bill of Rights is different: its s 33 does not exist."
    )
    assert _provisions(corpus, answer) == []


def test_a_bare_section_that_belongs_elsewhere_is_not_inferred(corpus):
    # Each of these was linked to a Canadian provision before it was excluded.
    answer = (
        "The Charter s 7 is narrower. Its gate is a hurdle NZBORA s 27(1) lacks.\n"
        "The Charter governs, but IRPA s 7 differs.\n"
        "*NZ contrast:* courts may declare inconsistency (the s 7 report).\n"
        "The Bill of Rights is quasi-constitutional (see ss 1–2 below)."
    )
    assert _provisions(corpus, answer) == [("s 7", "Constitution Act, 1982 s 7")]


def test_a_pinpoint_after_a_case_we_do_not_know_is_left_unmarked(corpus):
    answer = (
        "In *Oakes*, [1986] 1 SCR 103, the test (para 69), citing *Suresh* at para 70; "
        "the Chief Justice, Dickson CJ at para 71, and as in The Queen and Oakes (at para 72)."
    )
    found = _check(corpus, answer)
    assert "para 69" in found and "at para 71" in found  # a judge's name is not a case
    assert "at para 72" in found  # part of a known case's name is not another case
    assert "at para 70" not in found


def test_a_link_never_cuts_a_bold_short_name_in_half(corpus):
    answer = "R v Oakes, [1986] 1 SCR 103.\n- **The Queen and Oakes** paras 69, 70."
    assert "**The Queen and Oakes** paras 69, 70" in _check(corpus, answer)


def test_a_straight_apostrophe_matches_a_curly_one(corpus):
    names = verify._short_names(
        type(
            "C", (), {"case": lambda self, i: {"name": "Tsilhqot’in Nation v. British Columbia"}}
        )(),
        ["x"],
        [],
    )
    assert names == {"Tsilhqot'in": "x"}
    answer = "R v Oakes’ test, [1986] 1 SCR 103 at para 69."
    found = _check(corpus, answer, [f"{OAKES}#69"])
    assert "[1986] 1 SCR 103 at para 69" in found  # offsets survive the swap


def test_a_list_after_a_full_citation_is_part_of_its_pinpoint(corpus):
    found = _check(
        corpus,
        '"I would decide this appeal differently" ([1986] 1 SCR 103 at paras 69, 72). '
        "Also [1986] 1 SCR 103 at para 70, 2020 SCC 1.",
        [f"{OAKES}#{n}" for n in (69, 70, 72)],
    )
    listed = found["[1986] 1 SCR 103 at paras 69, 72"]
    assert listed.extra_unit_ids == [f"{OAKES}#72"]
    assert "quote not found at the pinpoint" not in listed.badges
    # The next citation's year is not a paragraph.
    assert found["[1986] 1 SCR 103 at para 70"].extra_unit_ids == []


def test_the_mark_says_what_was_checked_and_what_was_not(corpus):
    answer = '"I would decide this appeal differently" ([1986] 1 SCR 103 at paras 69–72).'
    found = _check(corpus, answer, [f"{OAKES}#{n}" for n in range(69, 73)])
    said = verify.explain(found["[1986] 1 SCR 103 at paras 69–72"])
    assert "paragraphs 69–72 exist, and the tutor read them" in said
    assert "the quoted words are there" in said
    assert "Not checked: that the passage says what the answer says it does" in said
    marked = verify.annotate(answer, list(found.values()))
    assert 'title="Checked by code' in marked and 'title="This passage is in dissenting' in marked


def test_a_list_of_sections_answers_for_every_section_in_it(corpus):
    answer = "Criminal Code ss 265, 266 apply."
    first, second = f"{CODE} s 265", f"{CODE} s 266"
    read_first = _check(corpus, answer, [first])["ss 265, 266"]
    assert read_first.status == "verified"
    assert read_first.badges == ["not read in context"]
    assert _check(corpus, answer, [first, second])["ss 265, 266"].badges == []


def test_a_list_with_a_section_not_held_is_not_verified(corpus):
    citation = _check(corpus, "Criminal Code ss 265, 999 apply.", [f"{CODE} s 265"])["ss 265, 999"]
    assert citation.status == "unverified"
    assert citation.badges == ["not in the corpus"]
