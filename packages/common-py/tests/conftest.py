from __future__ import annotations

import pytest

BASE_ENV = {
    "SM_SERVICE_NAME": "test-service",
    "SM_PG_PASSWORD": "pg-pass",
    "SM_INTERNAL_JWT_SIGNING_KEY": "internal-signing-key-0123456789",
    "SM_OIDC_CLIENT_SECRET": "oidc-secret",
}


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for k, v in BASE_ENV.items():
        monkeypatch.setenv(k, v)
    return dict(BASE_ENV)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from sm_common.config import _reset_cache_for_tests

    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()
