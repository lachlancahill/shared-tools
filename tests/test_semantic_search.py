"""Search uses the consumer's embedding/reranking and reports their combined cost."""

import pytest
from legal_corpus.search import Filters, semantic_search


@pytest.mark.parametrize("no_results", [False, True])
def test_injected_models_rank_real_local_results_and_only_charge_for_work(corpus, no_results):
    def embed(query):
        assert query == "test objective"
        return [1.0] * 8, 0.01

    def rerank(query, documents):
        assert not no_results  # no candidates must not incur a reranking call
        assert query == "test objective"
        return [float("sufficient importance" in doc) for doc in documents], 0.02

    text, cost = semantic_search(
        corpus,
        "test objective",
        Filters(kind="cases", courts=["NONE"] if no_results else []),
        embed_query=embed,
        rerank=rerank,
    )
    if no_results:
        assert text.startswith("No results")
        assert cost == pytest.approx(0.01)
    else:
        assert "1. R. v. Oakes" in text
        assert "sufficient importance" in text
        assert cost == pytest.approx(0.03)
