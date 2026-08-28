---
name: linux-client-whitebox-test-flow
description: Plan, execute, reopen, audit, and report evidence-backed Linux client white-box tests across multi-component releases and multi-node environments. Use when a request needs requirement-level traceability, controlled execution, or incremental retest and supplemental cycles; not for ordinary code review or unapproved product fixes.
---

# Linux Client White-box Test Flow

Organize Linux client testing as a recoverable requirement-level ledger. Verify
the environment and complete release bundle before testing, preserve every
execution cycle and report revision, and use the manifest rather than chat memory
to decide what may run next.

## Boundaries

- This skill owns stage detection, gates, release/environment binding, execution
  cycles, report revisions, audit, routing, and result synthesis.
- Use an available testing specialist or build/VM capability when it matches the
  environment; otherwise use documented repository entrypoints.
- Do not fix product behavior, install dependencies, change system configuration,
  restart shared environments, construct destructive fixtures, publish, or push
  unless that action is separately authorized.
- Continuous authorization never overrides a required permission or destructive,
  credential, environment, candidate, cleanup, failure, or scope-expansion pause.

## Before working

1. Read [references/workflow.md](references/workflow.md) and
   [references/quality-gates.md](references/quality-gates.md).
2. For a new, resumed, reopened, or changed run, read
   [references/run-manifest.md](references/run-manifest.md) and
   [references/environment-profile.md](references/environment-profile.md).
3. Validate, inspect, and audit the manifest:

```bash
python scripts/whitebox_flow.py validate <run-manifest.json>
python scripts/whitebox_flow.py status <run-manifest.json>
python scripts/whitebox_flow.py audit <run-manifest.json>
```

Schema v1 manifests are historical input. Migrate to a new file; never replace
the old ledger in place:

```bash
python scripts/whitebox_flow.py migrate old-run.json --output run-v2.json
```

Use `currentStage`, `currentCycle`, `missing`, and `nextRecommended`. Never
advance from conversation history when evidence, bundle identity, or record
coverage is missing.

## Environment and release bootstrap

Environment and release identity are prerequisites, not testing stages.

- Reuse the requirement's saved environment Profile and perform a read-only
  preflight on every run. Ask how to persist only a missing or newly observed
  Profile/fingerprint. Profiles store protected references, never credentials.
- Bind every participating build VM, test VM, datastore, GUI node, and privilege
  source by node ID. A single global credential alias is insufficient for a
  multi-node run.
- Build a `releaseBundle` containing every producer, consumer, service, helper,
  system component, and package that must be released together. Record component
  source/artifact SHA-256 values and bundle evidence.
- When the candidate changes, move the previous verified snapshot to
  `releaseBundleHistory`. Completed cycles keep their original bundle ID; only
  pending or active cycles may bind the current bundle.
- Stop before `intake` when the environment or bundle is unresolved, unavailable,
  or drifted. A changed component invalidates only evidence bound to the affected
  bundle; do not overwrite historical cycles.

## Initial stages

Advance the initial cycle in this order:

1. `intake`: identify requirement, Git source, full release bundle, objectives, record, and environment binding.
2. `discovery`: inspect changes, component/contract boundaries, tests/build/CI, dependencies, and risks.
3. `plan`: create requirement-risk-test-metric and producer-consumer compatibility matrices.
4. `test_assets`: implement or complete tests, fixtures, seams, fault injection, and registration.
5. `review`: review tests and minimum testability changes; only `PASS` permits a build.
6. `build`: build the exact release bundle in the bound environment.
7. `execution`: append an `INITIAL` execution cycle and collect raw evidence.
8. `report`: append a report revision that covers every completed, unreported cycle.

## Authorization modes

- `CHECKPOINTED`: after a stage, update the manifest and test record, run status,
  summarize evidence/gaps, and stop for `PROCEED`, `REWORK`, or `STOP`.
- `CONTINUOUS`: a recorded grant may cover named stages. Continue automatically
  only while all gates pass and the next stage is within its scope.

Both modes stop on failure, candidate change, environment drift, destructive
action, missing permission, unavailable credential, cleanup failure, or scope
expansion. Record the grant ID and scope so an automatic transition is auditable.

## Supplemental and retest cycles

Completing `report` sets lifecycle `REPORTED`; it does not freeze the ledger.
When later testing is authorized:

1. Set lifecycle to `REOPENED`, increment its revision, and record the reason.
2. Append a new `SUPPLEMENTAL` or `RETEST` cycle. Never reopen or overwrite the
   historical `INITIAL` cycle.
3. Bind the new cycle to the current release bundle and environment fingerprint.
4. Execute, verify cleanup, and append evidence-backed four-state results.
5. Append a new report revision and the same batch to the requirement test record.
6. Return lifecycle to `REPORTED`, or set `CLOSED` after an explicit close decision.

Maintain a UTF-8 JSON test-record index from
`assets/test-record-index.template.json`. Run `audit` before every report revision
and before `CLOSED`; it compares the index in both directions. Treat a document
batch missing from the manifest, an unreported cycle, missing/hash-mismatched
local evidence, or failed cleanup readback as an incomplete run.

## Execution invariants

- Keep `NOT_RUN`, `PASS`, `FAIL`, and `ENV_UNAVAILABLE` as the only test statuses.
  Add `reasonCategory` (`PRODUCT`, `COMPATIBILITY`, `FIXTURE`, `INFRA`, or
  `ENVIRONMENT`) to failures; scenario outcomes are separate annotations.
- If a change crosses process, version, persistence, datastore, IPC, or enum
  boundaries, plan old/old, old/new, new/old, and new/new compatibility cases.
- Reuse existing frameworks and build entrypoints. Test observable behavior and
  add only the smallest testability seam.
- Run fast tests before slower suites. Build and run ASan+UBSan separately from
  TSan; any sanitizer finding is `FAIL`.
- Use run-scoped setup and exact cleanup, then read state back. A completed cycle
  with unverified cleanup cannot pass audit.
- Use a UTF-8 locale and structured JSON for decision evidence where possible.
  Preserve commands, timestamps, exit codes, hashes, logs, screenshots, and raw
  metrics in the evidence index.
- After failure, perform read-only diagnosis. Product fixes, fixture mutation,
  rebuilds, and retests need authorization; limit one root cause to three rounds.

## Final report

Include release bundle/component identities, requirement and applicable
compatibility traceability, environment nodes/Profile, authorization mode, cycle and report
revision IDs, exact commands, four-state results and reason categories, first
failure symptom, coverage, sanitizer/performance evidence, cleanup readback,
uncovered risk, and recommendations. `CLOSED` means the ledger and requirement
record cover all completed cycles; it does not publish code automatically.
