from __future__ import annotations

import pytest

from ingestion_framework.secrets.openbao import reset_openbao_clients

# Every environment variable that steers OpenBao resolution. Tests set the
# handful they need; ambient values would otherwise take precedence and change
# the outcome. OPENBAO_TOKEN_FILE is the common case, since it is set on any
# host configured to talk to a real OpenBao and it outranks OPENBAO_TOKEN.
OPENBAO_ENV_VARS = (
    "OPENBAO_ADDR",
    "BAO_ADDR",
    "VAULT_ADDR",
    "OPENBAO_TOKEN_FILE",
    "BAO_TOKEN_FILE",
    "VAULT_TOKEN_FILE",
    "OPENBAO_TOKEN",
    "BAO_TOKEN",
    "VAULT_TOKEN",
    "OPENBAO_CACERT",
    "BAO_CACERT",
    "VAULT_CACERT",
    "OPENBAO_SKIP_VERIFY",
    "BAO_SKIP_VERIFY",
    "VAULT_SKIP_VERIFY",
)


@pytest.fixture(autouse=True)
def isolate_openbao_environment(monkeypatch):
    """Run every test against a clean OpenBao environment and client cache.

    The client cache is keyed on address and token, both of which tests reuse,
    so a client built with one test's fake session would otherwise be handed to
    the next.
    """
    for name in OPENBAO_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    reset_openbao_clients()
    yield
    reset_openbao_clients()
