"""Repo-root pytest configuration.

Unit tests must be hermetic: their result cannot depend on `SM_*` variables that
happen to be in the environment (a developer's exported `SM_ENV`, or the CI
job's own configuration). `pydantic-settings` reads OS environment variables
regardless of `_env_file=None`, so a stray `SM_ENV=ci` would leak into every
`AppSettings(...)` a test builds.

This autouse fixture strips `SM_*` from the environment for the duration of each
**non-integration** test. Integration tests keep the environment untouched —
`tests/integration/conftest.py` reads `SM_TEST_*` / `SM_PG_*` to find the real
services.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _hermetic_sm_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if request.node.get_closest_marker("integration"):
        yield
        return
    for key in list(os.environ):
        if key.startswith("SM_"):
            monkeypatch.delenv(key, raising=False)
    yield
