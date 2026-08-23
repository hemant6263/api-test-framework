"""Validates suites/product-create-list.yml against a mock shaped like the real API.

Response shapes mirror the real endpoints:
  POST   /user/product      -> ProductResponseDto, FLAT: {"id":.., "name":..}
  POST   /api/product       -> BaseResponseDto<Page<..>>, DOUBLE-wrapped:
                               {"data":{"content":[..],"totalElements":N},"success":true}
  GET    /user/product/{id} -> ProductResponseDto, flat
  DELETE /user/product/{id} -> void, 200, empty body
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
SUITE = Path(__file__).resolve().parents[2] / "suites" / "product-create-list.yml"
PID = 501


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    monkeypatch.setenv("AC_TOKEN", "mock-token")


def _runner() -> SuiteRunner:
    return SuiteRunner(
        env=EnvConfig(name="mock", base_url=BASE, timeout=5.0),
        transport=LiveHttpTransport(timeout=5.0))


def _product(name: str, pid: int = PID) -> dict:
    """Shaped like ProductResponseDto (flat; id from AbstractResponseCommonDto)."""
    return {"id": pid, "name": name, "description": "created by actf api test",
            "status": "ACTIVE", "riskScore": 0.0}


def _wrapped_page(rows: list[dict]) -> dict:
    """BaseResponseDto<Page<ProductResponseDto>>."""
    return {"data": {"content": rows, "totalElements": len(rows), "totalPages": 1,
                     "size": 100, "number": 0, "first": True, "last": True},
            "success": True, "timestamp": "22-08-2026 10:31:02"}


class _Api:
    """Stateful mock: create inserts, delete removes, search filters by name.

    `delete_delay_polls` models the real API, where DELETE is asynchronous: it
    returns 200 immediately but the product stays searchable for a few polls.
    """

    def __init__(self, *, delete_works: bool = True, delete_delay_polls: int = 0) -> None:
        self.rows: list[dict] = []
        self.name: str | None = None
        self.delete_works = delete_works
        self.delete_delay_polls = delete_delay_polls
        self._deleting = False

    def create(self, request):
        self.name = json.loads(request.content)["name"]
        self.rows = [_product(self.name)]
        return httpx.Response(200, json=_product(self.name))

    def search(self, request):
        if self._deleting:
            self.delete_delay_polls -= 1
            if self.delete_delay_polls <= 0:
                self.rows, self._deleting = [], False
        wanted = {n.lower() for n in json.loads(request.content).get("name") or []}
        hits = [r for r in self.rows
                if not wanted or r["name"].lower() in wanted]
        return httpx.Response(200, json=_wrapped_page(hits))

    def get_one(self, request):
        if not self.rows:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=self.rows[0])

    def delete(self, request):
        if not self.delete_works:
            return httpx.Response(200)
        if self.delete_delay_polls:
            self._deleting = True      # accepted, but not finished yet
        else:
            self.rows = []
        return httpx.Response(200)

    def install(self):
        respx.post(f"{BASE}/user/product").mock(side_effect=self.create)
        respx.post(f"{BASE}/api/product").mock(side_effect=self.search)
        respx.get(f"{BASE}/user/product/{PID}").mock(side_effect=self.get_one)
        return respx.delete(f"{BASE}/user/product/{PID}").mock(side_effect=self.delete)


def test_suite_file_parses_with_expected_steps():
    suite = load_suite(SUITE)
    assert [s.name for s in suite.steps] == [
        "create product", "find the product by name filter",
        "fetch the product by id", "delete product",
        "verify product no longer found"]
    assert suite.cleanup, "scenario must clean up after itself"


@respx.mock
def test_happy_path_create_find_fetch_delete_verify():
    api = _Api()
    delete = api.install()

    result = _runner().run(load_suite(SUITE))

    assert result.passed, result.failure_report()
    assert api.name.startswith("apitest-prod-"), "name must be uniquified per run"
    assert delete.called


@respx.mock
def test_search_sends_server_side_name_filter():
    """Must filter server-side; a client-side scan of an unfiltered list would
    break the moment the tenant has more than one page of products."""
    api = _Api()
    api.install()

    result = _runner().run(load_suite(SUITE))
    assert result.passed, result.failure_report()

    searches = [c for c in respx.calls if c.request.url.path == "/api/product"]
    assert searches, "search endpoint was never called"
    body = json.loads(searches[0].request.content)
    assert body["name"] == [api.name], f"must filter by created name, sent: {body}"


@respx.mock
def test_page_size_stays_within_the_api_limit():
    """POST /api/product returns 400 for size > 100."""
    api = _Api()
    api.install()

    _runner().run(load_suite(SUITE))

    searches = [c for c in respx.calls if c.request.url.path == "/api/product"]
    size = int(searches[0].request.url.params["size"])
    assert size <= 100, f"size={size} would be rejected with 400"


@respx.mock
def test_hard_delete_flag_is_sent():
    """Without ?delete=true the product is only soft-archived and would linger."""
    api = _Api()
    api.install()

    _runner().run(load_suite(SUITE))

    deletes = [c for c in respx.calls if c.request.method == "DELETE"]
    assert deletes, "delete was never called"
    assert deletes[0].request.url.params["delete"] == "true"


@respx.mock
def test_search_fails_when_created_product_is_absent():
    """The search step must prove presence, not merely return 200."""
    api = _Api()
    api.install()
    respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json=_wrapped_page([])))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert "find the product by name filter" in result.failure_report()


@respx.mock
def test_search_fails_when_id_does_not_match_the_created_product():
    """A same-name row with a different id must not pass as a match."""
    api = _Api()
    api.install()
    respx.post(f"{BASE}/api/product").mock(
        side_effect=lambda r: httpx.Response(
            200, json=_wrapped_page([_product(api.name, pid=9999)])))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert "9999" in result.failure_report()


@respx.mock
def test_verify_step_catches_a_delete_that_did_nothing():
    api = _Api(delete_works=False)
    api.install()

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert "verify product no longer found" in result.failure_report()


@respx.mock
def test_cleanup_removes_product_when_an_early_step_fails():
    """If create succeeds but search breaks, the product must not be orphaned.

    Create must echo back the generated name, else its own assertion fails and
    the chain stops before productId is ever captured.
    """
    def create(request):
        return httpx.Response(
            200, json=_product(json.loads(request.content)["name"]))

    respx.post(f"{BASE}/user/product").mock(side_effect=create)
    respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(500, json={"error": "boom"}))
    cleanup = respx.delete(f"{BASE}/user/product/{PID}").mock(
        return_value=httpx.Response(200))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert cleanup.called, "created product must be cleaned up despite the failure"


@respx.mock
def test_create_failure_stops_the_chain_immediately():
    """A 400 from create (e.g. duplicate name) must not cascade into search."""
    respx.post(f"{BASE}/user/product").mock(
        return_value=httpx.Response(400, json={"message": "Name already exists"}))
    search = respx.post(f"{BASE}/api/product").mock(
        return_value=httpx.Response(200, json=_wrapped_page([])))
    respx.delete(url__startswith=f"{BASE}/user/product/").mock(
        return_value=httpx.Response(200))

    result = _runner().run(load_suite(SUITE))

    assert not result.passed
    assert not search.called, "chain must stop at the failing create step"
    assert "Name already exists" in result.failure_report()


@respx.mock
def test_verify_step_polls_through_an_async_delete():
    """The real API returns 200 from DELETE before the product is actually gone.

    Without a retry the verify step fails on the first search. This models two
    polls' worth of lag.
    """
    api = _Api(delete_delay_polls=2)
    api.install()

    result = _runner().run(load_suite(SUITE))

    assert result.passed, result.failure_report()
    verify = result.steps[-1]
    assert verify.attempts > 1, "verify must have retried while the delete settled"
