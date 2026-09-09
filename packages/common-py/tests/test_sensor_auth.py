from __future__ import annotations

from typing import Any

import pytest

from sm_common.errors import Unauthenticated
from sm_common.security.sensor_auth import SensorAuth, _parse_credential


class ExplodingSession:
    """Any DB access is a test failure — the malformed-credential path must
    reject before touching the database."""

    async def scalar(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("SensorAuth touched the database for a malformed credential")

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("SensorAuth touched the database for a malformed credential")


@pytest.mark.parametrize(
    ("presented", "expected"),
    [
        ("11111111-1111-1111-1111-111111111111.s3cret", ("11111111-1111-1111-1111-111111111111", "s3cret")),
        ("Bearer 11111111-1111-1111-1111-111111111111.s3cret", ("11111111-1111-1111-1111-111111111111", "s3cret")),
        ("  id.secret.with.dots  ", ("id", "secret.with.dots")),
    ],
)
def test_parse_credential_ok(presented: str, expected: tuple[str, str]) -> None:
    assert _parse_credential(presented) == expected


@pytest.mark.parametrize("presented", ["", "no-dot-here", ".secret", "id.", "Bearer ", "   "])
def test_parse_credential_rejects_bad_shape(presented: str) -> None:
    assert _parse_credential(presented) is None


async def test_malformed_credential_is_generic_unauthenticated_without_db() -> None:
    auth = SensorAuth()
    with pytest.raises(Unauthenticated):
        await auth.authenticate(ExplodingSession(), presented_credential="not-a-credential")  # type: ignore[arg-type]


async def test_bad_uuid_is_generic_unauthenticated_without_db() -> None:
    auth = SensorAuth()
    with pytest.raises(Unauthenticated):
        await auth.authenticate(ExplodingSession(), presented_credential="not-a-uuid.secret")  # type: ignore[arg-type]
