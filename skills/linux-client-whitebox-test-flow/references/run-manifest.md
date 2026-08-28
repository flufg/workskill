# Run manifest schema v2

The manifest is the requirement-level test ledger. Start from
`assets/whitebox-run.template.json`; append cycles and report revisions rather
than overwriting previous results.

## Main records

- `lifecycle`: `ACTIVE`, `REPORTED`, `REOPENED`, or `CLOSED`, plus revision and reopen/close metadata.
- `target`: repository, Git ref, primary component, change type, requirement, and test-record reference.
- `releaseBundle`: state, bundle ID/SHA-256, every release component, and identity evidence.
- `releaseBundleHistory`: immutable prior bundle snapshots referenced by historical cycles.
- `environment`: Profile binding, fingerprint, participating node IDs, capabilities, and preflight evidence.
- `authorization`: `CHECKPOINTED` or scoped `CONTINUOUS` grant with mandatory pause conditions.
- `stages`: the initial eight-stage preparation/build/report state.
- `executionCycles`: immutable `INITIAL`, `RETEST`, and `SUPPLEMENTAL` batches.
- `reportRevisions`: append-only coverage of cycles and corresponding test-record batches.
- `testRecordIndexEvidence`: hashed structured index of batches recorded in the requirement document.
- `evidenceIndex`: stable IDs for files, receipts, commands, records, screenshots, and logs.

## Execution cycles

Each cycle records a unique ID, type, state, bundle ID, environment binding and
fingerprint, reason, timestamps, four-state result, cleanup readback, case
results, and evidence. `FAIL` and `ENV_UNAVAILABLE` case results require a reason
category. A completed cycle cannot have `NOT_RUN` as its aggregate result.

When a candidate changes, copy the previous verified bundle into
`releaseBundleHistory` before replacing the current bundle. Historical completed
cycles remain bound to their old ID; pending and active cycles must use the
current verified bundle.

After the initial report, set lifecycle `REOPENED` and append a new cycle. Do not
reset the eight stages or edit the old cycle. A report revision lists all newly
covered cycle IDs and the matching requirement-document batch ID.

## Lifecycle

```text
ACTIVE -> REPORTED -> REOPENED -> REPORTED -> CLOSED
```

- `REPORTED` means the current cycles are documented but more testing may be authorized.
- `REOPENED` requires a reason and at least one unreported cycle.
- `CLOSED` requires all cycles terminal, reported, audited, and cleaned.

## Compatibility

Set `scope.compatibility=true` when contracts cross version boundaries and
populate all four old/new producer-consumer combinations. The matrix uses the
same four result states as normal tests.

## Evidence and audit

Stage, cycle, result, bundle, environment, compatibility, and report fields refer
to evidence IDs. `LOCAL_FILE` entries need SHA-256; `REMOTE_RECEIPT` entries need
`verifiedAt` and `validationStatus`. Audit resolves local paths relative to the manifest directory and
checks report coverage and cleanup. Build the requirement-document sidecar from
`assets/test-record-index.template.json`, index it as `RECORD_INDEX`, and set
`testRecordIndexEvidence`; audit then detects both a document behind the manifest
and a manifest behind documented supplemental testing.

```bash
python scripts/whitebox_flow.py validate run.json
python scripts/whitebox_flow.py status run.json
python scripts/whitebox_flow.py audit run.json
```

Migrate v1 to a new path. Migration preserves legacy references as warnings and
sets unknown cleanup proof to false so it cannot silently claim a clean close:

```bash
python scripts/whitebox_flow.py migrate old.json --output run-v2.json
```
