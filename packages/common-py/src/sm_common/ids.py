"""Identifier generation.

`uuid7()` produces an RFC 9562 version-7 UUID: a 48-bit big-endian Unix
millisecond timestamp, then 74 random bits, with the version/variant nibbles
set. Version 7 is time-ordered, which is what the event envelope and database
primary keys want (index locality, natural sort). Python's stdlib gains
`uuid.uuid7()` only in 3.14, so we implement it here for 3.11.
"""

from __future__ import annotations

import os
import time
from uuid import UUID

__all__ = ["new_correlation_id", "new_request_id", "uuid7"]


def uuid7() -> UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = os.urandom(10)  # 80 random bits; 6 are overwritten by version/variant

    b = bytearray(16)
    b[0:6] = unix_ms.to_bytes(6, "big")
    b[6:16] = rand
    # version 7 in the high nibble of byte 6
    b[6] = 0x70 | (b[6] & 0x0F)
    # RFC 4122 variant (10xx) in the high bits of byte 8
    b[8] = 0x80 | (b[8] & 0x3F)
    return UUID(bytes=bytes(b))


def new_request_id() -> UUID:
    """Per-inbound-request identifier."""
    return uuid7()


def new_correlation_id() -> UUID:
    """Identifier that follows a logical operation across service and event hops."""
    return uuid7()
