from __future__ import annotations

from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from sm_ml.datasets.darpa_tc import (  # noqa: E402
    ProvenanceEntity,
    ProvenanceEvent,
    convert_cadets_e3_to_parquet,
    iter_cadets_e3_lines,
)
from sm_ml.datasets.darpa_tc_ground_truth import (  # noqa: E402
    load_orthrus_attack,
    load_threatrace_labels,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "darpa_tc"
_SYNTHETIC_FILE = "synthetic_cadets_e3.json"


def test_iter_cadets_e3_lines_parses_real_entity_shapes() -> None:
    records = list(iter_cadets_e3_lines(_FIXTURES / _SYNTHETIC_FILE))
    entities = {r.uuid: r for r in records if isinstance(r, ProvenanceEntity)}

    assert entities["S1"].entity_type == "subject"
    assert entities["S1"].label == "nginx"
    assert entities["F1"].entity_type == "file"
    assert entities["F1"].label == "/var/attacker/evil"
    assert entities["N1"].entity_type == "netflow"
    assert entities["N1"].label == "10.0.0.1:1234->8.8.8.8:80"
    # the Principal record and the malformed-JSON line are real-world noise
    # this adapter must skip, not crash on
    assert "P1" not in entities


def test_iter_cadets_e3_lines_excludes_and_filters_event_types() -> None:
    records = list(iter_cadets_e3_lines(_FIXTURES / _SYNTHETIC_FILE))
    events = {r.event_uuid: r for r in records if isinstance(r, ProvenanceEvent)}

    # EVENT_OTHER (E3) is a real excluded type; EVENT_UNLINK (E4) is a real
    # CDM18 type outside CADETS_E3's own 10-value vocabulary -- both dropped.
    assert "E3" not in events
    assert "E4" not in events
    assert set(events) == {"E1", "E2", "E5"}


def test_iter_cadets_e3_lines_reverses_read_direction() -> None:
    records = list(iter_cadets_e3_lines(_FIXTURES / _SYNTHETIC_FILE))
    events = {r.event_uuid: r for r in records if isinstance(r, ProvenanceEvent)}

    # EVENT_WRITE (E1): real direction kept as subject(S1) -> object(F1)
    assert (events["E1"].src_uuid, events["E1"].dst_uuid) == ("S1", "F1")
    # EVENT_READ (E2): real data flow is reversed -- object(F1) -> subject(S1)
    assert (events["E2"].src_uuid, events["E2"].dst_uuid) == ("F1", "S1")
    # EVENT_CONNECT (E5): not in REVERSED_EDGE_TYPES, kept as subject->object
    assert (events["E5"].src_uuid, events["E5"].dst_uuid) == ("S1", "N1")


def test_convert_cadets_e3_to_parquet_writes_real_entities_and_events(tmp_path: Path) -> None:
    result = convert_cadets_e3_to_parquet(_FIXTURES, tmp_path, (_SYNTHETIC_FILE,))

    entities_df = pl.read_parquet(result.entities_path)
    events_df = pl.read_parquet(result.events_path)

    assert entities_df.height == 3  # S1, F1, N1 -- not the skipped Principal
    assert set(entities_df["entity_type"].to_list()) == {"subject", "file", "netflow"}
    assert events_df.height == 3  # E1, E2, E5 -- excluded/unknown types dropped
    assert _SYNTHETIC_FILE in result.source_sha256
    assert len(result.source_sha256[_SYNTHETIC_FILE]) == 64  # real sha256 hex digest


def test_convert_cadets_e3_to_parquet_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        convert_cadets_e3_to_parquet(_FIXTURES, tmp_path, ("nonexistent.json",))


def test_load_threatrace_labels_deduplicates() -> None:
    labels = load_threatrace_labels(_FIXTURES / "threatrace_labels_sample.txt")
    # the sample fixture repeats "S1" once -- real upstream files do this too
    assert labels == frozenset({"S1", "F1", "N1"})


def test_load_orthrus_attack_attaches_real_window_and_uuids() -> None:
    attack = load_orthrus_attack(_FIXTURES / "node_Nginx_Backdoor_12.csv")
    assert attack.node_uuids == frozenset({"S1", "F1"})
    assert attack.window_start == "2018-04-12 13:59:00"
    assert attack.window_end == "2018-04-12 14:39:00"
    assert attack.used_in_pidsmaker_results is True


def test_load_orthrus_attack_unknown_filename_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "node_Unknown_Attack_99.csv"
    bogus.write_text("S1,{},1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no real attack window"):
        load_orthrus_attack(bogus)
