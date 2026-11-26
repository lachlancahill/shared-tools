# 0005 — ChatGPT plan access

- Date: 2026-11-15
- Status: accepted

## Context

OpenAI's "Sign in with ChatGPT" (2026-09-29) lets an app spend a ChatGPT subscriber's plan
allowance through the ordinary Responses API, with an OAuth access token in place of an API
key. One consumer built this privately first: plan first, API key when the plan cannot take
the call. Three consumers now want the same thing against **one shared sign-in**, and a
refresh token is spent by the refresh that uses it, so three copies of the refresh logic
drifting apart is how the connection would get broken.

## Decision

A fourth package, `chatgpt-plan` (module `chatgpt_plan`), holding the one implementation:

- `plan.Plan(database, document_path)`: the consumer passes its Firestore client and the
  path of the connection document. One `Plan` per process; it keeps the token in hand for
  its hour and the ten-minute rest after a refusal.
- `Plan.open_responses(request, api_client, timeout) -> (event_stream, on_plan)`: the one
  call-site change in a consumer. The request must stream.
- `Plan.access_token()`: the cached token, else the document, else a refresh under a
  60-second lease taken in a Firestore transaction. A refused refresh marks the document
  `broken`; a refresh with no answer does not.
- `sign_in.sign_in(connection, agent_name)`: the loopback browser sign-in, for a laptop.

## Why

- **The document is injected** because this repository is public and the connection is not:
  the package names no project, database, document, account or connection name. It also
  keeps credentials and singleton loading with the consumer, as 0001 does for the corpus.
- **A client and a path, not a document reference**, because the lease needs a transaction,
  and a transaction comes from the client. A reference only reaches its client through a
  private attribute.
- **Instance state, not module state**, so the tests need no patching of globals and a
  consumer could hold two connections if it ever had to.
- **Only a failure before any output falls back.** Mid-stream, words may already be on the
  reader's screen, and that failure is the caller's as for any provider. "Before any
  output" was first read as "before the stream starts" (a 429 at admission), and that was
  wrong: on 2026-11-20 a consumer's turns failed five times in ten minutes with *"The
  ChatGPT user has reached their Subscription Sharing usage limit"*, which arrived as the
  stream's first event after an HTTP 200 (the SDK raises it as `openai.APIError` from inside
  iteration). Nothing had been shown, nothing fell back, and the plan was never rested, so
  every retry asked it again. So `open_responses` reads the stream up to its **first words**
  (the first `.delta` event: answer text, a reasoning summary or a tool call's arguments);
  an error before then, raised or as an `error`/`response.failed` event, rests the plan and
  goes to the key, and otherwise every event read is replayed in front of the rest.
  The first version of this (2026-11-20) stopped at the first event that was not lifecycle
  (`response.created`, `in_progress`, `queued`). On 2026-11-25 a turn failed with the same
  limit after one more event: a stream announces its answer before it writes it
  (`output_item.added`, then `content_part.added`, measured on `gpt-6.1-sol`), and the read
  had stopped at the announcement. No consumer shows anything for an announcement, so the
  first `.delta` is where "before any output" really ends. Waiting for it costs nothing the
  reader can see: they see nothing until then either way.
- **A 400 falls back without resting the plan.** The rest exists because a limit lasts
  hours and asking again is a wasted round trip. A 400 is about one request: measured, a
  model the plan does not serve (`model_not_supported`) and a string `input`. Resting on it
  let one unsupported model send every other model's calls to the key for ten minutes.
- **Every plan call carries one `session_id` header per `Plan`.** Measured on
  `gpt-6.1-sol`: without it a repeated 1,200 to 9,000-token prompt hit the plan's prompt
  cache on 2 of 32 calls (the API key: 31 of 32, with no header). With it, 11 of 12, and a
  growing thread hit on every call after the first. `prompt_cache_key` alone did nothing,
  nor did spacing the calls. One id shared by three interleaved prompts still hit for each,
  so the id is per process, not per conversation. A second id does not read the first's
  cache; it warms its own. The header is what OpenAI's own Codex client sends; it is not in
  the plan-usage docs, so it is the first thing to re-measure if caching stops.
- **`httpx`, not `requests`**, for the token endpoint: the OpenAI SDK already brings it.
- `requires-python` is 3.12 here, not the workspace's 3.13: one consumer runs 3.12 and
  nothing in the package needs more.

## Alternatives considered

- **Each consumer keeps its own copy.** Three refreshers of one refresh token, with no test
  that they agree on the lease.
- **Environment variables for the document.** Configuration by side channel; the consumer
  already has a Firestore client and constants.
- **An async opener too.** No consumer is async; add it when one is.

## Consequences

- Consumers pin this package by git commit beside the others. It pulls `openai` and
  `google-cloud-firestore`, which every current consumer already has.
- What the plan accepts and refuses is measured by each consumer against its own request,
  and recorded there. Known when this was written: `stream=False` is a 400, `input` must be
  a list, not every API model is served (the refusal names the model),
  `max_output_tokens` is enforced, and reasoning written on the plan is silently ignored by
  the API key side after a fallback.
- The sign-in replaces the tokens every consumer shares. Run it only when the connection is
  logged as broken.
