# Run manifest

The manifest is the single source of progress for one test batch. Start from
`assets/whitebox-run.template.json` and validate it with the read-only status tool.

## Identity

- `schemaVersion`: currently `1`.
- `runId`: unique test-batch ID.
- `target`: repository, Git ref, component, change type, requirement, and test-record reference.
- `candidate`: source manifest SHA-256 and optional commit.
- `environment`: stable requirement-level binding, profile, capabilities, and preflight evidence.
- `scope`: selected test levels and optional capabilities.
- `stages`: the fixed eight-stage state.
- `approvals`: the decision after each completed stage.
- `testResults`: four-state case results.

Stage states are `PENDING`, `IN_PROGRESS`, `COMPLETED`, and `BLOCKED`. Decisions
are `PROCEED`, `REWORK`, and `STOP`. Completed stages need a summary and evidence;
blocked stages need a summary and missing list.

Every new test of the same requirement gets a new `runId` while retaining the
same test-record and environment binding unless an authorized replacement occurs.

```bash
python scripts/whitebox_flow.py validate run.json
python scripts/whitebox_flow.py status run.json
```

The script validates and reports only. It never edits the manifest, advances a
stage, builds code, or runs tests.
