"""Access to a ChatGPT plan (research/0005).

The refresh token is spent on every refresh, so losing the new one, or two instances
refreshing at once, means signing in from scratch. And when the plan cannot take a call, the
API key must, or the reader's turn fails for a reason that is only about who pays.

The Firestore here is a small in-memory stand-in: one document, and a transaction that runs
its function once, which is all the lease needs to be read against.
"""

import dataclasses
import time

import httpx
import openai
import pytest
from chatgpt_plan import plan
from google.cloud import firestore


class _Snapshot:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class _Document:
    def __init__(self, data=None):
        self.data, self.reads = data, 0

    def get(self, transaction=None):
        self.reads += 1
        return _Snapshot(self.data)

    def set(self, data):
        self.data = data

    def update(self, fields):
        self.data = {**self.data, **fields}


class _Transaction:
    def __init__(self, document):
        self._document = document

    def update(self, document, fields):
        document.update(fields)


class _Database:
    def __init__(self, data=None):
        self.stored = _Document(data)

    def document(self, path):
        return self.stored

    def transaction(self):
        return _Transaction(self.stored)


@pytest.fixture(autouse=True)
def plain_transactions(monkeypatch):
    """`firestore.transactional` retries against a real transaction; here it just runs."""
    monkeypatch.setattr(firestore, "transactional", lambda function: function)


def _credentials(expires_at: float, token: str = "old") -> plan.Credentials:
    return plan.Credentials(
        host_id="urn:uuid:host",
        client_id="oaiapp_x",
        access_token=token,
        refresh_token=f"{token}-refresh",
        id_token="id",
        expires_at=expires_at,
        scope=plan.SCOPES,
    )


def _connection(credentials: plan.Credentials, **fields) -> tuple[plan.Plan, _Document]:
    database = _Database({"credentials": dataclasses.asdict(credentials), **fields})
    return plan.Plan(database, "any/where"), database.stored


def _refreshed(sent: dict):
    def token(form):
        sent.update(form)
        return {
            "access_token": "new",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": plan.SCOPES,
        }

    return token


def test_a_due_token_is_refreshed_once_and_the_new_refresh_token_saved(monkeypatch):
    connection, document = _connection(_credentials(time.time()))
    sent = {}
    monkeypatch.setattr(plan, "_token", _refreshed(sent))

    assert connection.access_token() == "new"
    assert (sent["refresh_token"], sent["client_id"]) == ("old-refresh", "oaiapp_x")
    # The rotated refresh token is what the document now holds, the host id is kept, and
    # the save cleared the lease.
    saved = document.data["credentials"]
    assert (saved["refresh_token"], saved["host_id"]) == ("new-refresh", "urn:uuid:host")
    assert "refreshing_until" not in document.data
    # The hour is now in hand: no second refresh, and no second read of the document.
    monkeypatch.setattr(plan, "_token", lambda form: pytest.fail("refreshed twice"))
    reads = document.reads
    assert connection.access_token() == "new"
    assert document.reads == reads


def test_a_held_lease_sends_this_call_to_the_key(monkeypatch):
    connection, document = _connection(_credentials(time.time()), refreshing_until=time.time() + 30)
    monkeypatch.setattr(plan, "_token", lambda form: pytest.fail("refreshed under a lease"))
    assert connection.access_token() is None
    assert document.data["credentials"]["refresh_token"] == "old-refresh"


def test_a_lapsed_lease_is_taken_over(monkeypatch):
    connection, _ = _connection(_credentials(time.time()), refreshing_until=time.time() - 1)
    monkeypatch.setattr(plan, "_token", _refreshed({}))
    assert connection.access_token() == "new"


def test_the_lease_is_written_before_the_refresh(monkeypatch):
    connection, document = _connection(_credentials(time.time()))
    during = {}

    def token(form):
        during.update(document.data)
        return _refreshed({})(form)

    monkeypatch.setattr(plan, "_token", token)
    connection.access_token()
    assert during["refreshing_until"] > time.time()


def test_a_token_another_instance_refreshed_is_used_not_refreshed_again(monkeypatch):
    """Due at this instance's read, fresh by the time it asks for the lease."""
    connection, document = _connection(_credentials(time.time()))
    stale = dict(document.data)
    monkeypatch.setattr(connection, "read", lambda: stale)
    fresh = _credentials(time.time() + 3600, token="theirs")
    document.data = {"credentials": dataclasses.asdict(fresh)}
    monkeypatch.setattr(plan, "_token", lambda form: pytest.fail("refreshed twice"))
    assert connection.access_token() == "theirs"


def test_a_refused_refresh_marks_the_connection_broken(monkeypatch):
    connection, document = _connection(_credentials(time.time()))

    def refused(form):
        raise plan.Refused("refresh_token_reused")

    monkeypatch.setattr(plan, "_token", refused)
    assert connection.access_token() is None
    assert document.data["broken"] == "refresh_token_reused"
    # Broken stays broken: the next call does not try the spent token again.
    monkeypatch.setattr(plan, "_token", lambda form: pytest.fail("refreshed a broken connection"))
    assert connection.access_token() is None


def test_a_refresh_with_no_answer_is_tried_again(monkeypatch):
    connection, document = _connection(_credentials(time.time()))

    def unanswered(form):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(plan, "_token", unanswered)
    assert connection.access_token() is None
    assert "broken" not in document.data


def test_no_connection_goes_to_the_key():
    assert plan.Plan(_Database(), "any/where").access_token() is None


class _Responses:
    def __init__(self, outcome):
        self.outcome, self.calls, self.request = outcome, 0, None

    def create(self, **request):
        self.calls += 1
        self.request = request
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Client:
    def __init__(self, outcome):
        self.responses = _Responses(outcome)


def test_a_plan_refusal_falls_back_to_the_key_and_rests_the_plan(monkeypatch):
    over_limit = openai.RateLimitError(
        "subscription_sharing_usage_limit_exceeded",
        body=None,
        response=httpx.Response(429, request=httpx.Request("POST", plan.RESOURCE)),
    )
    plan_client, api_client = _Client(over_limit), _Client("api stream")
    connection, _ = _connection(_credentials(time.time() + 3600, token="plan"))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: plan_client)

    assert connection.open_responses({"model": "m"}, api_client, 10) == ("api stream", False)
    assert connection.open_responses({"model": "m"}, api_client, 10) == ("api stream", False)
    assert (plan_client.responses.calls, api_client.responses.calls) == (1, 2)
    assert api_client.responses.request == {"model": "m", "timeout": 10}


def test_a_refused_request_goes_to_the_key_without_resting_the_plan(monkeypatch):
    """A 400 is about the request (a model the plan does not serve), not the plan."""
    unsupported = openai.BadRequestError(
        "model_not_supported",
        body=None,
        response=httpx.Response(400, request=httpx.Request("POST", plan.RESOURCE)),
    )
    plan_client, api_client = _Client(unsupported), _Client("api stream")
    connection, _ = _connection(_credentials(time.time() + 3600, token="plan"))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: plan_client)

    assert connection.open_responses({}, api_client, 10) == ("api stream", False)
    assert connection.open_responses({}, api_client, 10) == ("api stream", False)
    assert plan_client.responses.calls == 2


def test_the_plan_is_asked_first_with_its_token(monkeypatch):
    connection, _ = _connection(_credentials(time.time() + 3600, token="plan"))
    made = {}

    def client(**kwargs):
        made.update(kwargs)
        return _Client("plan stream")

    monkeypatch.setattr(openai, "OpenAI", client)
    api_client = _Client("api stream")
    assert connection.open_responses({}, api_client, 10) == ("plan stream", True)
    assert (made["api_key"], made["base_url"], made["max_retries"]) == ("plan", plan.RESOURCE, 0)
    assert api_client.responses.calls == 0
    # Every call from one process shares a session id, or the plan's prompt cache misses.
    session = made["default_headers"]["session_id"]
    connection.open_responses({}, api_client, 10)
    assert made["default_headers"]["session_id"] == session


def test_a_sign_in_without_the_plan_scope_is_refused():
    body = {"scope": "openid profile", "access_token": "a", "refresh_token": "r", "id_token": "i"}
    with pytest.raises(plan.Refused):
        plan._credentials("urn:uuid:host", "oaiapp_x", body, time.time())
