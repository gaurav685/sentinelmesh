"""Enrichment providers.

An `Enricher` takes the freshly-mapped `CanonicalEventPayload` and returns a
provider-keyed dict that is merged into `payload.enrichment`, each carrying its
own provenance and freshness (event-model.md / R2). Geo-IP, hostname resolution,
identity stitching and threat-intel tagging are each an `Enricher`; none is
implemented yet, so the default provider list is empty and `enrichment` stays
`{}`.
"""

from __future__ import annotations

from .base import Enricher, run_enrichers

__all__ = ["Enricher", "run_enrichers"]
