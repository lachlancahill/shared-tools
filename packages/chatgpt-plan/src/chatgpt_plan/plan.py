"""Spending a ChatGPT plan before the API key, for every OpenAI call (research/0005).

OpenAI's "Sign in with ChatGPT" (2026-09-29) lets an app spend a ChatGPT subscriber's plan
allowance through the **ordinary Responses API**, `api.openai.com/v1/responses`, with an
OAuth access token in place of an API key. So a call goes to the plan first, and to the API
key when the plan cannot take it: not signed in, being refreshed by another instance, or
refused (over the plan's limit most of all). The reader never sees which; `open_responses`
tells the caller, so its usage record can.

This module is the token half and that one choice. The browser half, which needs a person
at a laptop, is `sign_in.py`.

**One connection, shared.** The tokens live in one Firestore document that every instance of
every consuming app reads. The consumer says which document: this package names no project,
database or document. A refresh token is spent by the refresh that uses it
(`refresh_token_reused` thereafter, and a sign-in from scratch), so two instances must never
refresh at once: one takes a short lease in a transaction and the others use the API key
until it is done.

Protocol, from developers.openai.com/siwc/token-sharing-open-source (read 2026-11-15):

* A first sign-in sends `client_id=dynamic_agent_client`, and the callback hands back the
  **issued** client id (`oaiapp_...`). That issued id is the one every exchange and refresh
  uses; `dynamic_agent_client` is never saved.
* `ext_agent_host_id` names the signing-in machine and must stay the same across sign-ins,
  so it is generated once and kept with the tokens.
* Access tokens last an hour; each refresh returns a new refresh token, good for 30 days.

Measured against the docs: `max_output_tokens` is *enforced*, not refused; `stream=False` is
a 400; reasoning replayed from the API is read on the plan, but **reasoning the plan wrote is
silently ignored by the API**, so a thread that falls back mid-way loses its earlier thinking
without an error. And **the plan's prompt cache only hits for requests that share a
`session_id` header**: without one, a repeated prompt was served from the cache on 2 of 32
calls, with one on 11 of 12 (the API key needs no such header). So every plan call from one
`Plan` carries the same id.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import secrets
import time
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    # Deferred, so a consumer that imports this at startup does not load either SDK until
    # its first OpenAI call.
    from google.cloud.firestore import Client
    from openai import OpenAI

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
# The audience of the access token, and where plan calls go. Sent on the authorize request,
# the exchange and every refresh; the docs say "the same `resource`" each time.
RESOURCE = "https://api.openai.com/v1"
# The registration entrypoint, never a client id to keep.
REGISTRATION_CLIENT_ID = "dynamic_agent_client"
# Identity, then plan usage. `offline_access` is what gets a refresh token at all, and
# `chatgpt.tokens.use.direct` is the one that permits spending the plan: a sign-in that
# comes back without it is refused below.
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
# A first registration must call back on this exact address; only the port may vary later,
# and `localhost` is refused.
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"
# Refresh this long before the hour is up, so a token never expires mid-stream.
REFRESH_MARGIN_SECONDS = 300
# How long one instance may hold the refresh before another may take it over. A refresh is
# one HTTP call; this only matters if the instance holding it dies mid-way.
LEASE_SECONDS = 60
# After the plan refuses a call, the API key takes every call for this long. The docs ask
# for a pause rather than a retry, and a limit is per five hours, so asking again on every
# call would add a refused round trip to each one for nothing.
PAUSE_SECONDS = 600
TOKEN_TIMEOUT_SECONDS = 30
FAILURE_EVENTS = frozenset({"error", "response.failed"})


@dataclasses.dataclass(frozen=True)
class Credentials:
    """One signed-in ChatGPT account."""

    host_id: str
    client_id: str
    access_token: str
    refresh_token: str
    id_token: str
    # Unix seconds, wall-clock: a token lifetime, not a date anybody reads.
    expires_at: float
    scope: str

    def expired(self, now: float) -> bool:
        return now >= self.expires_at - REFRESH_MARGIN_SECONDS


@dataclasses.dataclass(frozen=True)
class Authorization:
    """What one sign-in attempt has to remember between the browser and the callback."""

    url: str
    state: str
    nonce: str
    verifier: str


class Refused(RuntimeError):
    """OpenAI's token endpoint said no, as opposed to not answering."""


def new_host_id() -> str:
    """A host identifier: a random UUID, generated once and then kept.

    The docs accept `urn:uuid:` beside a JWK thumbprint; the thumbprint would mean keeping a
    key pair OpenAI never checks ("A host ID is not an authentication credential").
    """
    return f"urn:uuid:{uuid.uuid4()}"


def _challenge(verifier: str) -> str:
    """The PKCE S256 challenge: base64url SHA-256 of the verifier, without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization(host_id: str, agent_name: str) -> Authorization:
    """A first-registration authorize URL, with the secrets the callback is checked against.

    `agent_name` is what the consent screen and ChatGPT's "connected apps" settings call the
    connection.
    """
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    query = {
        "client_id": REGISTRATION_CLIENT_ID,
        "agent_name_hint": agent_name,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _challenge(verifier),
    }
    return Authorization(f"{AUTHORIZE_URL}?{urlencode(query)}", state, nonce, verifier)


def _claims(jwt: str) -> dict:
    """A JWT's payload, unverified.

    Not signature-checked, deliberately: the token came straight back from OpenAI's token
    endpoint over TLS in answer to our own request, which OpenID Connect accepts in place of
    checking the signature (Core 1.0, 3.1.3.7). What is checked is the nonce, which ties it to
    this sign-in.
    """
    payload = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _token(form: dict) -> dict:
    """One grant against the token endpoint. A 4xx is `Refused`: the grant itself is bad."""
    response = httpx.post(TOKEN_URL, data=form, timeout=TOKEN_TIMEOUT_SECONDS)
    if 400 <= response.status_code < 500:
        raise Refused(
            f"ChatGPT refused the {form['grant_type']} grant "
            f"({response.status_code}): {response.text}"
        )
    response.raise_for_status()
    return response.json()


def _credentials(host_id: str, client_id: str, body: dict, now: float) -> Credentials:
    if PLAN_SCOPE not in body["scope"].split():
        raise Refused(
            f"Signed in, but without `{PLAN_SCOPE}`, so the plan cannot be spent "
            f"(granted: {body['scope']})."
        )
    return Credentials(
        host_id=host_id,
        client_id=client_id,
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        id_token=body["id_token"],
        expires_at=now + body["expires_in"],
        scope=body["scope"],
    )


def exchange(host_id: str, client_id: str, code: str, auth: Authorization) -> Credentials:
    """Trade the callback's code for the first tokens, under the client id it issued."""
    body = _token(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": auth.verifier,
            "redirect_uri": REDIRECT_URI,
            "resource": RESOURCE,
        }
    )
    if _claims(body["id_token"]).get("nonce") != auth.nonce:
        raise Refused("The ID token's nonce is not this sign-in's; refusing it.")
    return _credentials(host_id, client_id, body, time.time())


def refresh(credentials: Credentials) -> Credentials:
    """A new access token, and with it the new refresh token that replaces the old one.

    `scope` is left out so the grant is kept as it is.
    """
    body = _token(
        {
            "grant_type": "refresh_token",
            "client_id": credentials.client_id,
            "refresh_token": credentials.refresh_token,
            "resource": RESOURCE,
        }
    )
    # A refresh may omit the ID token; the one from sign-in still identifies the account.
    body.setdefault("id_token", credentials.id_token)
    return _credentials(credentials.host_id, credentials.client_id, body, time.time())


class Plan:
    """One process's use of the shared connection.

    Make one per process and keep it: it holds the token in hand and how long the plan is
    resting after a refusal, so a call costs no Firestore read while the hour lasts.
    """

    def __init__(self, database: Client, document_path: str):
        """`database` is the consumer's Firestore client; `document_path` the connection
        document within it (`collection/document`)."""
        self._database = database
        self._document = database.document(document_path)
        self._cached: Credentials | None = None
        self._paused_until = 0.0
        # One id for everything this process sends. The plan routes requests that share it
        # to one prompt cache; measured, it works across interleaved conversations, so it
        # does not need to be per conversation.
        self._session_id = str(uuid.uuid4())

    # --- The shared document ---------------------------------------------------------------

    def read(self) -> dict | None:
        """The connection document: `credentials`, and `broken` or `refreshing_until` if set."""
        snapshot = self._document.get()
        return snapshot.to_dict() if snapshot.exists else None

    def save(self, credentials: Credentials) -> None:
        """Write fresh credentials, clearing any lease and any record of a broken connection."""
        self._document.set({"credentials": dataclasses.asdict(credentials)})

    def _mark_broken(self, reason: str) -> None:
        self._document.update({"broken": reason, "refreshing_until": 0})

    def _take_lease(self, now: float) -> Credentials | str | None:
        """Claim the refresh, unless somebody else has it or has already done it.

        Returns the credentials to refresh when the lease is ours, a current access token
        when another instance refreshed in the meantime, or None when another instance holds
        the lease.
        """
        from google.cloud import firestore

        document = self._document

        @firestore.transactional
        def claim(transaction):
            data = document.get(transaction=transaction).to_dict()
            credentials = Credentials(**data["credentials"])
            if not credentials.expired(now):
                return credentials.access_token
            if data.get("refreshing_until", 0) > now:
                return None
            transaction.update(document, {"refreshing_until": now + LEASE_SECONDS})
            return credentials

        return claim(self._database.transaction())

    # --- Choosing the plan or the key ------------------------------------------------------

    def access_token(self) -> str | None:
        """A current plan token, or None when this call should go to the API key instead.

        None, each with its reason logged: not signed in; the connection broken (a refresh
        refused, which only a new sign-in mends); resting after a refusal; another instance
        mid-refresh; or a refresh that did not get an answer, which the next call tries again.
        """
        now = time.time()
        if now < self._paused_until:
            return None
        if self._cached is not None and not self._cached.expired(now):
            return self._cached.access_token

        data = self.read()
        if data is None:
            logger.warning("No ChatGPT plan connection; run the sign-in.")
            return None
        if data.get("broken"):
            logger.warning(
                "The ChatGPT plan connection is broken (%s); run the sign-in.", data["broken"]
            )
            return None
        credentials = Credentials(**data["credentials"])
        if not credentials.expired(now):
            self._cached = credentials
            return credentials.access_token

        claimed = self._take_lease(now)
        if claimed is None or isinstance(claimed, str):
            return claimed
        try:
            self._cached = refresh(claimed)
        except Refused as error:
            # The refresh token is gone, and every later refresh would be refused the same way.
            logger.error(
                "ChatGPT plan refresh refused; the API key takes every OpenAI call until the "
                "sign-in is run again. %s",
                error,
            )
            self._mark_broken(str(error))
            return None
        except httpx.HTTPError:  # boundary: no answer is not a refusal; try again later
            logger.warning("ChatGPT plan refresh got no answer; using the API key.", exc_info=True)
            return None
        self.save(self._cached)
        return self._cached.access_token

    def pause(self, error: Exception) -> None:
        """Rest the plan after it refused a call, so the next calls go straight to the key."""
        self._paused_until = time.time() + PAUSE_SECONDS
        logger.warning(
            "ChatGPT plan refused a call; the API key takes OpenAI calls for %d minutes. %s",
            PAUSE_SECONDS // 60,
            error,
        )

    def open_responses(
        self, request: dict, api_client: OpenAI, timeout: float
    ) -> tuple[object, bool]:
        """Start a streamed Responses call on the plan, or on the API key when it cannot be.

        Returns the event stream and whether the plan is paying. A refusal **before any
        output** falls back: an error at admission, or an error in the stream before its first
        words. The plan's usage limit arrives the second way (an HTTP 200, then *"The ChatGPT
        user has reached their Subscription Sharing usage limit"*), so the stream is read up to
        its first words before it is returned, and every event read is replayed to the caller.
        A failure *after* output is the caller's, as any provider failure is, because by then
        words may be on the reader's screen.

        A refusal rests the plan (`pause`), except a 400: that is about the request, not the
        plan. A caller that knows a request will be refused (a model the plan does not serve)
        should not ask, because each ask is a wasted round trip.

        The request must stream: the plan refuses `stream=False`. `timeout` applies to
        whichever side takes the call.
        """
        import openai

        token = self.access_token()
        if token is not None:
            client = openai.OpenAI(
                api_key=token,
                base_url=RESOURCE,
                timeout=timeout,
                max_retries=0,  # the API key is the retry
                default_headers={"session_id": self._session_id},
            )
            try:
                stream = client.responses.create(**request)
                # One iterator, read from here and then handed on, so nothing is read twice.
                # Inside the try: the SDK raises `APIError` from iteration for an error event.
                events = iter(stream)
                read = _read_to_first_output(events)
                if read and read[-1].type in FAILURE_EVENTS:
                    stream.close()
                    raise _FailedBeforeOutput(read[-1])
                return _replay(read, events), True
            except openai.BadRequestError as error:
                # Boundary: the plan refused *this request* (a model or a field it does not
                # serve), which says nothing about the next one. The key takes this call and
                # the plan is not rested.
                logger.warning("ChatGPT plan refused a request; the API key takes it. %s", error)
            except (openai.APIError, _FailedBeforeOutput) as error:
                # Boundary: whatever stopped the plan before a word was streamed, the API key
                # can take this call, and the ones after it for a while. `APIError` covers a
                # refused status, no connection, and an error event raised from the stream.
                self.pause(error)
        return api_client.responses.create(**request, timeout=timeout), False


class _FailedBeforeOutput(RuntimeError):
    """The plan accepted the call and then failed it before producing anything."""

    def __init__(self, event: object) -> None:
        super().__init__(f"The plan's stream failed before any output: {event}")


def _read_to_first_output(events) -> list:
    """Read the stream's events up to and including its first words, or the plan failing it.

    Words are a `.delta` event (answer text, a reasoning summary, a tool call's arguments).
    Everything before one only announces what is coming (`response.created`,
    `output_item.added`, `content_part.added` and the like), so nothing is on anyone's screen
    yet and the API key can still take the call. Stopping at the first event that was not
    lifecycle, as this did until 2026-11-26, missed a usage limit sent after
    `output_item.added`. Every event read is returned, so none is lost when the stream is
    handed on. A stream that ends with no words returns what it had; the caller sees an
    ordinary short stream.
    """
    read = []
    for event in events:
        read.append(event)
        if event.type.endswith(".delta") or event.type in FAILURE_EVENTS:
            break
    return read


def _replay(read: list, events):
    """The events already read, then the rest of the stream."""
    yield from read
    yield from events
