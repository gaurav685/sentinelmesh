# @sentinelmesh/contracts

TypeScript types for the frontend, **generated** from the SentinelMesh JSON
Schema contracts. Do not hand-edit anything under `src/` or `schemas/`.

## Regenerate

```
cd packages/contracts-ts
npm install            # one-time: installs json-schema-to-typescript
npm run generate       # runs ../../scripts/gen_contracts.py
```

`schemas/*.json` is produced from `packages/contracts-py` (Pydantic v2, the
source of truth). `src/*.ts` is produced from `schemas/*.json`.

## CI

```
npm run check          # fails if committed schema is stale vs sm_contracts
```
