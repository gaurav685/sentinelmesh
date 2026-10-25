"""DARPA Transparent Computing (TC) CADETS E3 provenance-graph adapter.

See `docs/PHASE2_PLAN.md` for provenance and `docs/DOWNLOAD_VIA_OWN_DRIVE.md`
for how the raw data is obtained (a real Google Drive public-link quota
blocks the direct anonymous download; this module works unchanged once the
real files are in place, regardless of which path got them there).

Real CDM18 JSON-line record format (confirmed by reading
`ubc-provenance/PIDSMaker`'s own working parser directly, not guessed or
assumed from documentation -- that repo's `dataset_preprocessing/darpa_tc/
create_database_e3.py`, Apache-2.0, is the real reference this module's
field names/types were checked against):

    {"datum": {"com.bbn.tc.schema.avro.cdm18.Subject": {...}}, ...}
    {"datum": {"com.bbn.tc.schema.avro.cdm18.FileObject": {...}}, ...}
    {"datum": {"com.bbn.tc.schema.avro.cdm18.NetFlowObject": {...}}, ...}
    {"datum": {"com.bbn.tc.schema.avro.cdm18.Event": {...}}, ...}

Each real audit-log file is one CDM record per line (JSON Lines), not a
single JSON document -- this module streams line-by-line and never loads a
whole file into memory, same discipline as Phase 1's Parquet conversion
(a real memory crisis there is the reason, see
`sm_ml.datasets.parquet_convert`'s own docstring).

Three entity (node) types, ten real event (edge) types -- matching
`num_node_types=3`/`num_edge_types=10` in PIDSMaker's own CADETS_E3 dataset
config, cross-checked, not assumed to match by coincidence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .common import file_sha256

__all__ = [
    "EDGE_TYPES",
    "EXCLUDED_EDGE_TYPES",
    "REVERSED_EDGE_TYPES",
    "ConversionResult",
    "ProvenanceEntity",
    "ProvenanceEvent",
    "convert_cadets_e3_to_parquet",
    "iter_cadets_e3_lines",
]

_SUBJECT_KEY = "com.bbn.tc.schema.avro.cdm18.Subject"
_FILE_KEY = "com.bbn.tc.schema.avro.cdm18.FileObject"
_NETFLOW_KEY = "com.bbn.tc.schema.avro.cdm18.NetFlowObject"
_EVENT_KEY = "com.bbn.tc.schema.avro.cdm18.Event"
_UUID_KEY = "com.bbn.tc.schema.avro.cdm18.UUID"

EntityType = Literal["subject", "file", "netflow"]

# Real 10-value edge-type vocabulary, matching PIDSMaker's `rel2id_darpa_tc`
# (`pidsmaker/utils/dataset_utils.py`) -- cross-checked against
# `num_edge_types=10` in its CADETS_E3 dataset config, not assumed.
EDGE_TYPES: tuple[str, ...] = (
    "EVENT_CONNECT", "EVENT_EXECUTE", "EVENT_OPEN", "EVENT_READ", "EVENT_RECVFROM",
    "EVENT_RECVMSG", "EVENT_SENDMSG", "EVENT_SENDTO", "EVENT_WRITE", "EVENT_CLONE",
)

# Real-event types with no corresponding system call, or no usable predicate
# object -- dropped before graph construction, same convention as
# PIDSMaker's `exclude_edge_type` (cross-checked, not reinvented).
EXCLUDED_EDGE_TYPES: frozenset[str] = frozenset({
    "EVENT_FCNTL", "EVENT_OTHER", "EVENT_ADD_OBJECT_ATTRIBUTE", "EVENT_FLOWS_TO",
})

# Event types whose real subject/object direction is the reverse of what the
# CDM record's own subject/predicateObject fields say (e.g. EVENT_READ's
# "subject" reads FROM its object, so the real data-flow edge points
# object->subject) -- same convention as PIDSMaker's `edge_reversed`,
# restricted to the 10 edge types this dataset actually uses (that list also
# covers EVENT_LSEEK/EVENT_MMAP/EVENT_ACCEPT/etc., real CDM18 event types
# that exist but aren't in CADETS_E3's own 10-value vocabulary above).
REVERSED_EDGE_TYPES: frozenset[str] = frozenset({
    "EVENT_EXECUTE", "EVENT_OPEN", "EVENT_READ", "EVENT_RECVFROM", "EVENT_RECVMSG",
})


@dataclass(frozen=True)
class ProvenanceEntity:
    uuid: str
    entity_type: EntityType
    label: str  # cmdline (subject) / path (file) / "addr:port" (netflow)


@dataclass(frozen=True)
class ProvenanceEvent:
    event_uuid: str
    src_uuid: str
    dst_uuid: str
    edge_type: str
    timestamp_ns: int


@dataclass(frozen=True)
class ConversionResult:
    entities_path: Path
    events_path: Path
    source_sha256: dict[str, str]


def _unwrap(value: Any) -> Any:
    """CDM18's avro-JSON encoding wraps an optional scalar as `{"string": x}`
    / `{"int": x}` rather than `x` directly, or omits it as `None` -- this
    unwraps either real shape to the plain value, defaulting to `None`."""
    if isinstance(value, dict):
        for v in value.values():
            return v
        return None
    return value


def _parse_subject(datum: dict[str, Any]) -> ProvenanceEntity:
    cmdline = _unwrap(datum.get("cmdLine"))
    return ProvenanceEntity(uuid=datum["uuid"], entity_type="subject", label=str(cmdline or ""))


def _parse_file(datum: dict[str, Any]) -> ProvenanceEntity:
    base = datum.get("baseObject") or {}
    props = (base.get("properties") or {}).get("map") or {}
    path = props.get("path") or props.get("filename") or base.get("path") or base.get("filename") or ""
    return ProvenanceEntity(uuid=datum["uuid"], entity_type="file", label=str(path))


def _parse_netflow(datum: dict[str, Any]) -> ProvenanceEntity:
    local_addr = _unwrap(datum.get("localAddress"))
    local_port = _unwrap(datum.get("localPort"))
    remote_addr = _unwrap(datum.get("remoteAddress"))
    remote_port = _unwrap(datum.get("remotePort"))
    label = f"{local_addr}:{local_port}->{remote_addr}:{remote_port}"
    return ProvenanceEntity(uuid=datum["uuid"], entity_type="netflow", label=label)


def _parse_event(datum: dict[str, Any]) -> ProvenanceEvent | None:
    edge_type = datum.get("type")
    if edge_type in EXCLUDED_EDGE_TYPES or edge_type not in EDGE_TYPES:
        return None
    subject = datum.get("subject") or {}
    predicate_object = datum.get("predicateObject") or {}
    subject_uuid = subject.get(_UUID_KEY)
    object_uuid = predicate_object.get(_UUID_KEY)
    if not subject_uuid or not object_uuid:
        return None
    timestamp_ns = datum.get("timestampNanos")
    if timestamp_ns is None:
        return None
    src, dst = (object_uuid, subject_uuid) if edge_type in REVERSED_EDGE_TYPES else (subject_uuid, object_uuid)
    return ProvenanceEvent(
        event_uuid=datum["uuid"], src_uuid=src, dst_uuid=dst,
        edge_type=edge_type, timestamp_ns=int(timestamp_ns),
    )


def iter_cadets_e3_lines(path: Path) -> Iterator[ProvenanceEntity | ProvenanceEvent]:
    """Stream one real CDM18 JSON-lines file, yielding each real entity
    (`Subject`/`FileObject`/`NetFlowObject`) and event (`Event`) record in
    file order. A line that fails to parse as JSON, or whose `datum` is none
    of the four known types, is silently skipped (CADETS E3's real files are
    known to carry other CDM18 record types -- `Principal`, `Host`,
    `TimeMarker`, etc. -- this adapter only needs the four above)."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            datum_wrapper = record.get("datum")
            if not isinstance(datum_wrapper, dict) or len(datum_wrapper) != 1:
                continue
            (type_key, datum), = datum_wrapper.items()
            if type_key == _SUBJECT_KEY:
                yield _parse_subject(datum)
            elif type_key == _FILE_KEY:
                yield _parse_file(datum)
            elif type_key == _NETFLOW_KEY:
                yield _parse_netflow(datum)
            elif type_key == _EVENT_KEY:
                event = _parse_event(datum)
                if event is not None:
                    yield event


def convert_cadets_e3_to_parquet(raw_dir: Path, out_dir: Path, filenames: tuple[str, ...]) -> ConversionResult:
    """Stream every named real CDM18 JSON-lines file once, writing
    `out_dir/entities.parquet` (uuid, entity_type, label -- deduplicated,
    last write wins per uuid, matching CDM's own "objects can be
    re-published with updated attributes" semantics) and
    `out_dir/events.parquet` (event_uuid, src_uuid, dst_uuid, edge_type,
    timestamp_ns). Real sha256 of every input file is returned alongside
    the two output paths so a caller can record real provenance, same
    convention as `parquet_convert.convert_cicids2017_to_parquet`.

    Entities are buffered in a dict (bounded by the real number of distinct
    CADETS_E3 nodes -- 178,965 per KAIROS's own measurement, trivial RAM),
    events are buffered in a list before one `pl.DataFrame` write -- real
    event count (~10.1M per KAIROS) is comfortably within this project's
    ~10 GB RAM budget as plain Python tuples; switch to a streaming sink if
    a future dataset's real event count ever makes that untrue."""
    import polars as pl

    out_dir.mkdir(parents=True, exist_ok=True)
    entities: dict[str, ProvenanceEntity] = {}
    events: list[ProvenanceEvent] = []
    hashes: dict[str, str] = {}

    for name in filenames:
        path = raw_dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing CADETS E3 file: {path}")
        hashes[name] = file_sha256(path)
        for record in iter_cadets_e3_lines(path):
            if isinstance(record, ProvenanceEntity):
                entities[record.uuid] = record
            else:
                events.append(record)

    entities_df = pl.DataFrame(
        {
            "uuid": [e.uuid for e in entities.values()],
            "entity_type": [e.entity_type for e in entities.values()],
            "label": [e.label for e in entities.values()],
        }
    )
    events_df = pl.DataFrame(
        {
            "event_uuid": [e.event_uuid for e in events],
            "src_uuid": [e.src_uuid for e in events],
            "dst_uuid": [e.dst_uuid for e in events],
            "edge_type": [e.edge_type for e in events],
            "timestamp_ns": [e.timestamp_ns for e in events],
        }
    )

    entities_path = out_dir / "entities.parquet"
    events_path = out_dir / "events.parquet"
    entities_df.write_parquet(entities_path, compression="zstd")
    events_df.write_parquet(events_path, compression="zstd")

    return ConversionResult(entities_path=entities_path, events_path=events_path, source_sha256=hashes)
