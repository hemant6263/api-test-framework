"""Validates suites/user-lifecycle.yml against a mock shaped like the real API.

Proves the scenario's logic (chaining, server-side email search, verify-gone)
without needing QA. If the YAML drifts into something the engine can't run, or
the assertions stop actually proving anything, these fail.

Response shapes mirror the real endpoints:
  POST /user/add/user        -> NameIdPair, flat: {"id":.., "name":..}
  POST /api/v2/user/search   -> BaseResponseDto<Page<..>>, double-wrapped:
                                {"data":{"content":[..],"totalElements":N},"success":true}
  DELETE /user/data/remove/{id} -> void, 200, empty body
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from actf import SuiteRunner, load_suite
from actf.model import EnvConfig
from actf.transport import LiveHttpTransport

BASE = "https://mock.test"
SUITE = Path(__file__).resolve().parents[2] / "suites" / "user-lifecycle.yml"
UID = 99


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    """The suite declares auth: bearer, which reads AC_TOKEN."""
    monkeypatch.setenv("AC_TOKEN", "mock-token")


def _runner() -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0))


def _row(email: str, uid: int = UID) -> dict:
    """Shaped like UserResponseTenantDto."""
    return {"userId": uid, "email": email, "name": "API Test User",
            "tenantRole": "admin", "disableLogin": False}


def _page(rows: list[dict]) -> dict:
    """BaseResponseDto<Page<UserResponseTenantDto>>."""
    return {"data": {"content": rows, "totalElements": len(rows),
                     "totalPages": 1, "size": 100, "number": 0},
            "success": True, "timestamp": "01-01-2026 00:00:00"}


class _Api:
    """Stateful mock: create inserts, delete removes, search filters by email."""

    def __init__(self, *, delete_works: bool = True) -> None:
        self.rows: list[dict] = []
        self.email: str | None = None
        self.delete_works = delete_works

    def create(self, request):
        self.email = json.loads(request.content)["email"]
        self.rows = [_row(self.email)]
        return httpx.Response(200, json={"id": UID, "name": "API Test User"})

    def search(self, request):
        wanted = set(json.loads(request.content).get("email") or [])
        hits = [r for r in self.rows if r["email"] in wanted] if wanted else self.rows
        return httpx.Response(200, json=_page(hits))

    def delete(self, request):
        if self.delete_works:
            self.rows = []
        return httpx.Response(200)

    def install(self):
        respx.post(f"{BASE}/user/add/user").mock(side_effect=self.create)
        respx.post(f"{BASE}/api/v2/user/search").mock(side_effect=self.search)
        return respx.delete(url__startswith=f"{BASE}/user/data/remove/").mock(
            side_effect=self.delete)


def test_suite_file_parses_with_expected_steps():
    suite = load_suite(SUITE)
    assert [s.name for s in suite.steps] == [
        "create user", "search for the created user by email",
        "delete user", "verify user is gone"]
    assert suite.cleanup, "scenario must clean up after itself"


@respx.mock
def test_happy_path_create_search_delete_verify():
    api = _Api()
    delete = api.install()

    result = _runner().run(load_suite(SUITE))

    assert result.passed, result.failure_report()
    assert api.email.startswith("apitest-") and api.email.endswith("@example.com"), \
        "email must be uniquified per run so reruns don't collide"
    assert delete.called


@respx.mock
def test_search_sends_server_side_email_filter_not_a_full_list_pull():
    """The search must filter server-side; a client-side scan would be wrong."""
    api = _Api()
    api.install()

    result = _runner().run(load_suite(SUITE))

    assert result.passed, result.failure_report()
    search_calls = [c for c in respx.calls
                    if c.request.url.path == "/api/v2/user/search"]
    assert search_calls, "search endpoint was never called"
    body = json.loads(search_calls[0].request.content)
    assert body["email"] == [api.email], \
        f"search must filter by the created email, sent: {body}"


@respx.mock
def test_search_fails_when_created_user_is_absent():
    """Search must prove presence, not merely return 200."""
    api = _Api()
    api.install()
    # search returns a different user entirely
    respx.post(f"{BASE}/api/v2/user/search").mock(
        return_value=httpx.Response(200, json=_page([_row("someone.else@x.io", 1)])))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert "search for the created user by email" in result.failure_report()


@respx.mock
def test_search_fails_when_id_does_not_match_the_created_user():
    """A same-email row with a different id must not pass as a match."""
    api = _Api()
    api.install()
    respx.post(f"{BASE}/api/v2/user/search").mock(
        side_effect=lambda r: httpx.Response(
            200, json=_page([_row(api.email, uid=12345)])))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    report = result.failure_report()
    assert "userId" in report and "12345" in report


@respx.mock
def test_verify_step_catches_a_delete_that_did_nothing():
    """The whole point of step 4 — a delete that lies must be caught."""
    api = _Api(delete_works=False)
    api.install()

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert "verify user is gone" in result.failure_report()


@respx.mock
def test_cleanup_removes_user_when_an_early_step_fails():
    """If create succeeds but search breaks, the user must not be orphaned."""
    respx.post(f"{BASE}/user/add/user").mock(
        return_value=httpx.Response(200, json={"id": UID, "name": "API Test User"}))
    respx.post(f"{BASE}/api/v2/user/search").mock(
        return_value=httpx.Response(500, json={"error": "boom"}))
    cleanup = respx.delete(f"{BASE}/user/data/remove/{UID}").mock(
        return_value=httpx.Response(200))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert cleanup.called, "created user must be cleaned up despite the failure"


@respx.mock
def test_create_failure_stops_the_chain_immediately():
    """A 400 from create (e.g. bad tenantRole) must not cascade into search."""
    respx.post(f"{BASE}/user/add/user").mock(
        return_value=httpx.Response(
            400, json={"message": "Provided Tenant Role Not Found nope"}))
    search = respx.post(f"{BASE}/api/v2/user/search").mock(
        return_value=httpx.Response(200, json=_page([])))
    respx.delete(url__startswith=f"{BASE}/user/data/remove/").mock(
        return_value=httpx.Response(200))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert not search.called, "chain must stop at the failing create step"
    # the API's own error text must reach the report, for a usable failure message
    assert "Tenant Role Not Found" in result.failure_report()
