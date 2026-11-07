# shared-tools

Two Python 3.13+ libraries, with no web app or model client:

- **legal-core**: dependency-free citation parsing/resolution and decision-text parsing.
- **legal-corpus**: read-only snapshot loading, keyword/vector search, graph queries,
  reading in context, and citation/quotation checking. Depends on legal-core,
  DuckDB, LanceDB, PyArrow and NumPy. Imports these only when their modules are used.

The libraries were extracted from the private legal-assistant project. The code is
public; **no corpus, judgment PDFs, NZLII cache or credentials are included**.
The default profiles name a private bucket. Knowing its name grants no access.
Consumers need their own read-only GCS role and application default credentials;
tests use small local snapshots with no network. NZ reader fixtures are invented.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run main.py  # import smoke check, no corpus load
```

Read [`research/README.md`](research/README.md) before changing the boundary.

## Read a snapshot

```python
from dataclasses import replace
from legal_corpus.profile import NEW_ZEALAND
from legal_corpus.snapshot import Corpus
from legal_corpus.reader import read
from legal_corpus.search import Filters, keyword_search
from legal_corpus.verify import verify

# An absolute local directory, or gs://bucket/prefix. No credentials are stored here.
profile = replace(NEW_ZEALAND, corpus_uri="/absolute/path/to/nz-corpus")
corpus = Corpus(profile)
results = keyword_search(corpus, '"discovery"', Filters(kind="legislation"))
passage = read(corpus, "HCR r 8.4")
checked = verify(corpus, "The rule is HCR r 8.4.", set(passage.unit_ids))
```

The directory has `current.json` with a `snapshot` relative path, naming an immutable
snapshot of graph parquet files, `manifest.json`, `syllabus.json`, and a LanceDB
`search/units` table. `snapshot.TABLES` lists required graph columns. Graph metadata
is loaded into memory; paragraph text stays in LanceDB, queried in place on GCS.
SQL access is sealed against file/network access after load. Each query has its own
DuckDB cursor. The consumer owns caching, reloads and lifetime; the library has no
process-wide corpus singleton.

`CANADA` uses `CORPUS_URI` if set; `NEW_ZEALAND` defaults to that URI's `/nz` prefix.
Use `dataclasses.replace` for another snapshot location or consumer-specific links.
The default links are the tutor's reader routes; a different app must replace
`link_prefix` or render its own citation targets, not assume those routes exist.

## Semantic search and checking

`semantic_search` and `semantic_groups` require keyword-only `embed_query` and
`rerank` callables. They return `(text_or_groups, cost_usd)`; embedding returns
`(vector, cost_usd)` and reranking returns `(scores_in_document_order, cost_usd)`.
The embedding must match the published index's model and dimensions. The current
index uses Qwen3-Embedding-8B, 1024 dimensions, and Qwen3-Reranker-4B. Provider
credentials, prompts, network calls and charging belong to the consumer.

`read` returns text and unit ids. Keep those ids per turn: `verify` marks an unread
pinpoint even when it exists. `check_conversation` carries reads and cited cases
forward for short-form references. `nz_needed(texts, loader)` optionally calls a
consumer-supplied NZ loader for mixed Canadian/NZ answers. An NZ-only consumer can
pass its NZ corpus directly to `verify`/`check_conversation`.

Checks establish that citations resolve, pinpoints exist, quotations occur there,
and passages were read; they flag dissent, revocation and known negative treatment.
**They do not establish that a passage supports the model's legal proposition, or
that the corpus is complete or current.** Inspect `Citation.status` and `badges`,
not just a count of resolved citations.

## Consume from Git

`legal_corpus.nz_skill` packages NZ-only research instructions (`prose()`) and
six tool contracts (`TOOLS`) without importing DuckDB/LanceDB or a snapshot.
Consumers adapt these to their tool dispatcher and enforce their own permissions,
read history, model charges and checker display. There is no NCA comparison canon
tool in this skill. The Markdown resource is included in the wheel.

Consumers pin **both** packages to the same published commit using uv git sources
with `subdirectory = "packages/legal-core"` / `"packages/legal-corpus"`. During
development, uv editable path sources can point at this checkout. Do not deploy a
consumer lock that still names a path outside its Docker build context.

No licence has been selected yet; public visibility is not a licence grant.
