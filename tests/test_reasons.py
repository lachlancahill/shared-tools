"""Whose reasons speak for the Court: majorities counted, not taken from the label."""

from legal_corpus.reasons import classify, describe, judges_in

# Benches and authors lines as the corpus holds them; `joined` as the ingest now keeps
# the report's "were delivered by" statement.
MIKISEW_BENCH = [
    "Wagner, Richard",
    "Abella, Rosalie Silberman",
    "Moldaver, Michael J.",
    "Karakatsanis, Andromache",
    "Gascon, Clément",
    "Côté, Suzanne",
    "Brown, Russell",
    "Rowe, Malcolm",
    "Martin, Sheilah",
]
MIKISEW = [
    {"kind": "majority", "authors": "Karakatsanis J. (Wagner C.J. and Gascon J. concurring)"},
    {"kind": "concurring", "authors": "Abella J. (Martin J. concurring)"},
    {"kind": "concurring", "authors": "Brown J."},
    {"kind": "concurring", "authors": "Rowe J. (Moldaver and Côté JJ. concurring)"},
]


def test_a_majority_label_on_three_of_nine_is_a_plurality():
    kinds = classify(MIKISEW, MIKISEW_BENCH)
    assert kinds[MIKISEW[0]["authors"]] == ("plurality", 3)
    assert kinds[MIKISEW[3]["authors"]] == ("concurring", 3)
    assert describe("plurality", 3, MIKISEW_BENCH) == "plurality: 3 of 9 judges, no majority"


def test_a_real_majority_stays_one():
    vavilov = [
        {
            "kind": "majority",
            "authors": "Wagner C.J. and Moldaver, Gascon, Côté, Brown, Rowe and Martin JJ.",
        },
        {"kind": "concurring", "authors": "Abella and Karakatsanis JJ."},
    ]
    assert judges_in(vavilov[0]["authors"], MIKISEW_BENCH) == 7
    assert classify(vavilov, MIKISEW_BENCH)[vavilov[0]["authors"]] == ("majority", 7)


SINGH_BENCH = [
    "Dickson, Robert George Brian",
    "Beetz, Jean",
    "Estey, Willard Zebedee",
    "McIntyre, William Rogers",
    "Lamer, Antonio",
    "Wilson, Bertha",
]


def test_an_even_split_named_in_delivered_by_statements_has_no_majority():
    singh = [
        {
            "kind": "unknown",
            "authors": "Wilson J.",
            "joined": "Dickson C.J. and Lamer and Wilson JJ.",
        },
        {"kind": "unknown", "authors": "Beetz J.", "joined": "Beetz, Estey and McIntyre"},
    ]
    assert {k for k, _ in classify(singh, SINGH_BENCH).values()} == {"plurality"}


def test_the_judgment_of_the_court_is_unanimous():
    bell = [
        {"kind": "unknown", "authors": "The Chief Justice and Bastarache J.", "joined": "the Court"}
    ]
    assert classify(bell, MIKISEW_BENCH)[bell[0]["authors"]] == ("majority", 9)


def test_a_majority_joined_in_its_statement_with_writers_alone_for_the_rest():
    bench = SINGH_BENCH[:1] + [
        "Beetz, Jean",
        "McIntyre, William Rogers",
        "Chouinard, Julien",
        "Lamer, Antonio",
        "Wilson, Bertha",
        "Le Dain, Gerald Eric",
    ]
    motor_vehicle = [
        {
            "kind": "unknown",
            "authors": "Lamer J.",
            "joined": "Dickson C.J. and Beetz, Chouinard, Lamer and Le Dain JJ.",
        },
        {"kind": "unknown", "authors": "McIntyre J.", "joined": None},
        {"kind": "unknown", "authors": "Wilson J.", "joined": None},
    ]
    kinds = classify(motor_vehicle, bench)
    assert kinds["Lamer J."] == ("majority", 5)
    assert kinds["McIntyre J."] == ("separate", 1)  # beside a majority: not a plurality


def test_reasons_whose_judges_cannot_be_counted_keep_their_label():
    assert classify([{"kind": "majority", "authors": "The Court"}], MIKISEW_BENCH) == {
        "The Court": ("majority", 0)
    }
    # Writers named without who joined them: two names of nine leave room for either
    # to be a majority, so the labels stand.
    writers = [
        {"kind": "majority", "authors": "Abella J."},
        {"kind": "concurring", "authors": "Brown J."},
    ]
    assert classify(writers, MIKISEW_BENCH)["Abella J."] == ("majority", 1)


def test_counts_short_of_the_bench_can_still_rule_out_a_majority():
    # Norberg v Wynrib: 3, 2 and 1 counted of 7. The missing judge cannot make 3 a
    # majority of 7 (4 of 7 would be), so it is undecided, and the labels stand.
    bench = ["A, a", "B, b", "C, c", "D, d", "E, e", "F, f", "G, g"]
    norberg = [
        {"kind": "unknown", "authors": "A J.", "joined": "A, B and C JJ."},
        {"kind": "unknown", "authors": "D J.", "joined": "D and E JJ."},
        {"kind": "unknown", "authors": "F J.", "joined": None},
    ]
    assert classify(norberg, bench)["A J."] == ("unknown", 3)
    # With nobody missing, 3, 2 and 2 of 7 is no majority at all.
    norberg[2]["joined"] = "F and G JJ."
    assert {k for k, _ in classify(norberg, bench).values()} == {"plurality"}


def test_upper_case_authors_are_counted():
    assert judges_in("BEETZ J.", SINGH_BENCH) == 1


def test_an_incomplete_bench_decides_nothing():
    # Grdic v The Queen: the bench lists 4 of 7 judges, so Lamer J's five-judge
    # reasons matched one name and looked like separate reasons.
    bench = ["Dickson, Brian", "Beetz, Jean", "Lamer, Antonio", "Wilson, Bertha"]
    grdic = [
        {
            "kind": "unknown",
            "authors": "Wilson J.",
            "joined": "Dickson C.J. and Beetz and Wilson JJ.",
        },
        {
            "kind": "unknown",
            "authors": "Lamer J.",
            "joined": "Estey, McIntyre, Lamer, Le Dain and La Forest JJ.",
        },
    ]
    assert {k for k, _ in classify(grdic, bench).values()} == {"unknown"}


def test_names_are_counted_from_the_text():
    from legal_corpus.reasons import names_given

    assert names_given("Karakatsanis J. (Wagner C.J. and Gascon J. concurring)") == 3
    assert names_given("Wagner C.J. and Moldaver, Gascon, Côté, Brown, Rowe and Martin JJ.") == 7
    assert names_given("Bastarache J. (dissenting)") == 1
    # The authors line and the headnote's Per line name the same judges: three, not six.
    assert (
        names_given(
            "Karakatsanis J. (Wagner C.J. and Gascon J. concurring) "
            "Wagner C.J. and Karakatsanis and Gascon JJ."
        )
        == 3
    )


def test_mikisew_with_its_headnote_per_lines_is_still_a_plurality():
    with_per = [dict(s) for s in MIKISEW]
    with_per[0]["joined"] = "Wagner C.J. and Karakatsanis and Gascon JJ."
    with_per[3]["joined"] = "Moldaver, Côté and Rowe JJ."
    assert classify(with_per, MIKISEW_BENCH)[MIKISEW[0]["authors"]] == ("plurality", 3)
