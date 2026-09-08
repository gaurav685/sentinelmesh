from __future__ import annotations

import time

from sm_common.ids import uuid7


def test_uuid7_version_and_variant():
    u = uuid7()
    assert u.version == 7
    assert (u.int >> 62) & 0b11 == 0b10  # RFC 4122 variant


def test_uuid7_time_ordered():
    a = uuid7()
    time.sleep(0.005)
    b = uuid7()
    # first 48 bits are a millisecond timestamp
    assert (a.int >> 80) <= (b.int >> 80)
    assert a != b


def test_uuid7_unique_batch():
    seen = {uuid7() for _ in range(2000)}
    assert len(seen) == 2000
