"""Corporate CA bundle resolution.

Behind a TLS-inspecting proxy (Zscaler/Netskope) httpx fails with
CERTIFICATE_VERIFY_FAILED because certifi does not carry the proxy's root CA,
even when curl and the JVM work fine. The transport honours the same env vars
the rest of the toolchain already uses.
"""
from __future__ import annotations

import pytest

from actf.transport.live_http import _CA_ENV_VARS, resolve_ca_bundle


@pytest.fixture(autouse=True)
def _clear_ca_env(monkeypatch):
    for var in _CA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_returns_none_when_nothing_is_configured():
    assert resolve_ca_bundle() is None


@pytest.mark.parametrize("var", _CA_ENV_VARS)
def test_each_supported_env_var_is_honoured(monkeypatch, tmp_path, var):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv(var, str(ca))
    assert resolve_ca_bundle() == str(ca)


def test_actf_specific_var_wins_over_the_generic_ones(monkeypatch, tmp_path):
    mine = tmp_path / "mine.pem"
    other = tmp_path / "other.pem"
    for p in (mine, other):
        p.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("SSL_CERT_FILE", str(other))
    monkeypatch.setenv("ACTF_CA_BUNDLE", str(mine))
    assert resolve_ca_bundle() == str(mine)


def test_missing_file_is_ignored_rather_than_breaking_the_client(monkeypatch, tmp_path):
    """A stale SSL_CERT_FILE pointing at a deleted file must not crash startup —
    fall through to certifi instead."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "gone.pem"))
    assert resolve_ca_bundle() is None


def test_tilde_paths_are_expanded(monkeypatch, tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SSL_CERT_FILE", "~/ca.pem")
    assert resolve_ca_bundle() == str(ca)


def test_transport_builds_with_a_custom_bundle(monkeypatch, tmp_path):
    """httpx loads the bundle eagerly, so a real cert is needed here."""
    from actf.transport import LiveHttpTransport

    ca = tmp_path / "ca.pem"
    ca.write_text(_SELF_SIGNED_PEM)
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))

    t = LiveHttpTransport(timeout=5.0, verify_tls=True)
    t.close()


def test_verify_disabled_skips_bundle_resolution(monkeypatch, tmp_path):
    """verifyTls: false in an env file must not be overridden by a stray var."""
    from actf.transport import LiveHttpTransport

    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "nonexistent.pem"))
    t = LiveHttpTransport(timeout=5.0, verify_tls=False)
    t.close()


# A throwaway self-signed cert, only used to prove httpx accepts a custom bundle.
_SELF_SIGNED_PEM = """-----BEGIN CERTIFICATE-----
MIIBhTCCASugAwIBAgIQIRi6zePL6mKjOipn+dNuaTAKBggqhkjOPQQDAjASMRAw
DgYDVQQKEwdBY21lIENvMB4XDTE3MTAyMDE5NDMwNloXDTE4MTAyMDE5NDMwNlow
EjEQMA4GA1UEChMHQWNtZSBDbzBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABD0d
7VNhbWvZLWPuj/RtHFjvtJBEwOkhbN/BnnE8rnZR8+sbwnc/KhCk3FhnpHZnQz7B
5aETbbIgmuvewdjvSBSjYzBhMA4GA1UdDwEB/wQEAwICpDATBgNVHSUEDDAKBggr
BgEFBQcDATAPBgNVHRMBAf8EBTADAQH/MCkGA1UdEQQiMCCCDmxvY2FsaG9zdDo1
NDUzgg4xMjcuMC4wLjE6NTQ1MzAKBggqhkjOPQQDAgNIADBFAiEA2zpJEPQyz6/l
Wf86aX6PepsntZv2GYlA5UpabfT2EZICICpJ5h/iI+i341gBmLiAFQOyTDT+/wQc
6MF9+Yw1Yy0t
-----END CERTIFICATE-----
"""
