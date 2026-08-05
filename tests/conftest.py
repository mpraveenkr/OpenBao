from __future__ import annotations

import pytest

from ingestion_framework.secrets.openbao import reset_openbao_clients


@pytest.fixture(autouse=True)
def reset_openbao_client_cache():
    """Keep the per-process OpenBao client cache from leaking between tests.

    The cache is keyed on address and token, which tests reuse, so a client
    built with one test's fake session would otherwise be handed to the next.
    """
    reset_openbao_clients()
    yield
    reset_openbao_clients()
