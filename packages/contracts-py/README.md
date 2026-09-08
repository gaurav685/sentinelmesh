# sm-contracts

Canonical SentinelMesh contracts. Single source of truth for:

- the canonical **event envelope** (`EventEnvelope[PayloadT]`)
- the canonical **API error contract** (`ErrorResponse`)
- **Phase-1 entity DTOs** (`Tenant`, `User`, `Role`, `Permission`, `Sensor`,
  `AuditRecord`, …) — safe shapes, never the database models
- **Phase-1 API request/response** models
- shared **enums**

TypeScript types for the frontend are generated from the JSON Schema this
package emits — see `scripts/gen_contracts.py` (repo root) → `packages/contracts-ts/`.

## Rules

- Every model forbids unknown fields (`extra="forbid"`).
- All identifiers are `uuid.UUID`; all datetimes are timezone-aware, normalized
  to UTC.
- Contract status (STABLE / DRAFT / PLANNED): see `docs/CONTRACTS.md`.
- Breaking a STABLE contract requires bumping `CONTRACTS_VERSION`
  (`sm_contracts.version`).

## Install (dev)

```
python -m venv .venv
. .venv/Scripts/activate      # Windows;  source .venv/bin/activate on POSIX
pip install -e "packages/contracts-py[dev]"
pytest packages/contracts-py
```

## Use

```python
from sm_contracts import EventEnvelope, UserEventPayload, ErrorResponse, User
```
