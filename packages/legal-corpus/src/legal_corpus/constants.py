"""Bounds on corpus retrieval and tool output, shared by every consumer."""

SEARCH_MAX_CASES = 10
SEARCH_SNIPPETS_PER_CASE = 2
SNIPPET_CHARS = 600
# Candidates fetched before priors, grouping and semantic reranking.
SEARCH_CANDIDATES = 50
VECTOR_NPROBES = 20
VECTOR_REFINE_FACTOR = 5
CITING_MAX_ROWS = 20
CITING_SNIPPET_CHARS = 500
READ_CONTEXT = 2
READ_MAX_CHARS = 12_000
PROVISION_DEFINITIONS_MAX = 8
DEFINITION_CHARS = 700
CO_CITED_MAX = 15
# Neighbouring provisions stay under the same heading, at most this many either side.
PROVISION_NEIGHBOURS = 12
