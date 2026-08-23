"""Placeholder resolution — type preservation and failure messages."""
from __future__ import annotations

import pytest

from actf.ctx import SuiteContext
from actf.evaluators import ResolveError


def test_sole_placeholder_preserves_type():
    ctx = SuiteContext(variables={"id": 42, "flag": True, "obj": {"a": 1}})
    assert ctx.resolve("${id}") == 42 and isinstance(ctx.resolve("${id}"), int)
    assert ctx.resolve("${flag}") is True
    assert ctx.resolve("${obj}") == {"a": 1}


def test_embedded_placeholder_interpolates_as_string():
    ctx = SuiteContext(variables={"id": 42})
    assert ctx.resolve("/api/finding/${id}") == "/api/finding/42"


def test_deep_resolution_through_dicts_and_lists():
    ctx = SuiteContext(variables={"id": 7, "n": "x"})
    out = ctx.resolve({"a": ["${id}", "p-${n}"], "b": {"c": "${id}"}})
    assert out == {"a": [7, "p-x"], "b": {"c": 7}}


def test_unknown_variable_names_available_ones():
    ctx = SuiteContext(variables={"productId": 1})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${findingId}")
    msg = str(exc.value)
    assert "findingId" in msg and "productId" in msg


def test_env_evaluator_and_default(monkeypatch):
    monkeypatch.setenv("ACTF_X", "vv")
    ctx = SuiteContext()
    assert ctx.resolve("${env:ACTF_X}") == "vv"
    assert ctx.resolve("${env:ACTF_NOPE:-fallback}") == "fallback"


def test_missing_env_var_is_an_error_not_empty_string(monkeypatch):
    monkeypatch.delenv("ACTF_ABSENT", raising=False)
    with pytest.raises(ResolveError) as exc:
        SuiteContext().resolve("${env:ACTF_ABSENT}")
    assert "ACTF_ABSENT" in str(exc.value)


def test_uuid_is_unique_per_call():
    ctx = SuiteContext()
    assert ctx.resolve("${uuid}") != ctx.resolve("${uuid}")


def test_self_referencing_variable_terminates():
    ctx = SuiteContext(variables={"a": "${a}"})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${a}")
    assert "nesting" in str(exc.value)


def test_non_placeholder_values_pass_through():
    ctx = SuiteContext()
    assert ctx.resolve(42) == 42
    assert ctx.resolve(None) is None
    assert ctx.resolve("plain") == "plain"


def test_custom_evaluator_is_registered():
    class VaultEvaluator:
        prefix = "vault"

        def evaluate(self, expr, ctx):
            return f"secret::{expr}"

    ctx = SuiteContext(evaluators=[VaultEvaluator()])
    assert ctx.resolve("${vault:db/pw}") == "secret::db/pw"


# --- drilling into captured objects / lists ---------------------------------

def test_dotted_access_into_captured_object():
    ctx = SuiteContext(variables={"user": {"id": 9, "email": "a@b.io"}})
    assert ctx.resolve("${user.email}") == "a@b.io"
    assert ctx.resolve("${user.id}") == 9


def test_deep_nested_access():
    ctx = SuiteContext(variables={"u": {"team": {"bu": {"id": 5}}}})
    assert ctx.resolve("${u.team.bu.id}") == 5


def test_list_indexing_including_negative():
    ctx = SuiteContext(variables={"ids": [10, 20, 30]})
    assert ctx.resolve("${ids[0]}") == 10
    assert ctx.resolve("${ids[-1]}") == 30


def test_mixed_index_and_key_access():
    ctx = SuiteContext(variables={"rows": [{"id": 7, "tags": ["a", "b"]}]})
    assert ctx.resolve("${rows[0].id}") == 7
    assert ctx.resolve("${rows[0].tags[1]}") == "b"


def test_accessor_preserves_type_and_interpolates_in_strings():
    ctx = SuiteContext(variables={"u": {"id": 9, "team": {"id": 5}}})
    assert ctx.resolve("${u.id}") == 9, "sole placeholder keeps the int"
    assert ctx.resolve("/api/u/${u.id}/t/${u.team.id}") == "/api/u/9/t/5"


def test_whole_collection_passes_through_untouched():
    """Capturing a list/dict and reusing it wholesale must not stringify it."""
    ctx = SuiteContext(variables={"ids": [1, 2], "obj": {"a": 1}})
    assert ctx.resolve("${ids}") == [1, 2]
    assert ctx.resolve("${obj}") == {"a": 1}
    assert ctx.resolve({"body": "${ids}"}) == {"body": [1, 2]}


def test_variable_names_with_hyphens_still_resolve():
    ctx = SuiteContext(variables={"my-var": "ok"})
    assert ctx.resolve("${my-var}") == "ok"


def test_missing_key_lists_available_keys():
    ctx = SuiteContext(variables={"user": {"id": 9, "email": "a@b.io"}})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${user.nope}")
    msg = str(exc.value)
    assert "nope" in msg and "email" in msg


def test_index_out_of_range_reports_length():
    ctx = SuiteContext(variables={"ids": [1, 2, 3]})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${ids[9]}")
    assert "out of range" in str(exc.value) and "3" in str(exc.value)


def test_accessing_into_a_scalar_is_an_error():
    ctx = SuiteContext(variables={"id": 42})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${id.x}")
    assert "cannot read" in str(exc.value)


def test_unknown_root_still_reports_unknown_variable():
    ctx = SuiteContext(variables={"a": 1})
    with pytest.raises(ResolveError) as exc:
        ctx.resolve("${nosuch.field}")
    assert "unknown variable" in str(exc.value)
