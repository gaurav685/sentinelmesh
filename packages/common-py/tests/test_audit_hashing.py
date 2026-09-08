from __future__ import annotations

from sm_common.audit import GENESIS_HASH, canonical_json, compute_entry_hash, verify_chain


def _row(i: int) -> dict:
    return {"action": "login", "seq": i, "actor": "u1", "result": "success"}


def test_canonical_json_deterministic():
    a = {"b": 1, "a": 2, "c": [3, 1]}
    b = {"c": [3, 1], "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert b" " not in canonical_json(a)


def test_hash_is_stable_and_prev_sensitive():
    r = _row(1)
    h1 = compute_entry_hash(GENESIS_HASH, r)
    assert h1 == compute_entry_hash(GENESIS_HASH, dict(r))
    assert compute_entry_hash("f" * 64, r) != h1
    assert len(h1) == 64


def test_verify_chain_ok():
    entries = []
    prev = GENESIS_HASH
    for i in range(5):
        row = _row(i)
        h = compute_entry_hash(prev, row)
        entries.append((h, row))
        prev = h
    assert verify_chain(entries) is True


def test_verify_chain_detects_tamper():
    entries = []
    prev = GENESIS_HASH
    for i in range(3):
        row = _row(i)
        h = compute_entry_hash(prev, row)
        entries.append((h, row))
        prev = h
    # alter a row body without recomputing hashes
    tampered = list(entries)
    stored_hash, row = tampered[1]
    tampered[1] = (stored_hash, {**row, "result": "failure"})
    assert verify_chain(tampered) is False


def test_verify_chain_detects_reorder():
    entries = []
    prev = GENESIS_HASH
    for i in range(3):
        row = _row(i)
        h = compute_entry_hash(prev, row)
        entries.append((h, row))
        prev = h
    entries[1], entries[2] = entries[2], entries[1]
    assert verify_chain(entries) is False
