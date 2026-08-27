---
name: linux-client-whitebox-test-flow
description: Plan, implement, review, build, execute, and report auditable white-box tests for Linux client changes. Use for checkpointed testing across unit, integration, fault-injection, sanitizer, performance, service, or GUI paths; not for ordinary code review or unapproved product fixes.
---

# Linux Client White-box Test Flow

Organize Linux client white-box testing as a recoverable, evidence-backed stage
flow. Resolve and verify an environment profile before `intake`, detect the
recorded progress, execute only the current authorized stage, then stop for the
user's decision.

## Boundaries

- This skill owns stage detection, gates, routing, handoffs, and result synthesis.
- Use an available testing specialist or build/VM tool when it matches the target
  environment. Otherwise use the repository's documented test and build entrypoints.
- Do not claim code review passed without recorded review evidence.
- Do not fix product behavior, install dependencies, change system configuration,
  restart shared environments, publish, or push unless separately authorized.

## Before working

1. Read [references/workflow.md](references/workflow.md).
2. Read [references/quality-gates.md](references/quality-gates.md).
3. For a new or updated run, read
   [references/run-manifest.md](references/run-manifest.md) and
   [references/environment-profile.md](references/environment-profile.md).
4. Create a run manifest from the template if one does not exist, then validate
   and inspect it:

```bash
python scripts/whitebox_flow.py validate <run-manifest.json>
python scripts/whitebox_flow.py status <run-manifest.json>
```

Use `currentStage`, `missing`, and `nextRecommended` from the status output.
Never advance based only on chat history when required evidence is absent.

## Environment bootstrap

Environment bootstrap is a prerequisite, not one of the eight testing stages.

1. Check the run manifest, requirement test record, configured private profile
   registry, and project profile registry for a matching environment profile.
2. If no readable profile matches, stop and ask the user for the build/test
   platform, access method, toolchain/profile, commands or capability providers,
   supported test capabilities, evidence collection, cleanup, and protected
   credential references. Never ask for secret values to place in the profile.
3. Ask where to keep a newly configured environment:
   - `PRIVATE`: reusable user-private profile outside the public repository;
   - `PROJECT`: sanitized project profile suitable for sharing, with no secrets;
   - `SESSION`: use only for this run and do not persist it.
4. Write or reference the profile only after the user chooses. Record its binding
   ID, reference, expected fingerprint, capabilities, persistence, and evidence.
5. For JSON profiles, validate the selected profile before use:

```bash
python scripts/environment_profile.py validate <environment-profile.json>
```

6. Run a read-only preflight. Set the manifest environment state to `VERIFIED`
   only when the observed fingerprint matches and required capabilities exist.

If a previously unknown environment or new fingerprint is encountered, do not
silently save it. Ask whether to save it as `PRIVATE` or `PROJECT`, use it for
the current `SESSION`, keep the existing binding, or stop. Do not enter `intake`
until the selected environment is `VERIFIED`.

## Stages

Advance strictly in this order:

1. `intake`: identify requirement, Git source, candidate, objectives, record, and environment binding.
2. `discovery`: inspect changes, module boundaries, existing tests/build/CI, dependencies, and risks.
3. `plan`: create a requirement-risk-test-metric matrix with commands, pass criteria, and cleanup.
4. `test_assets`: implement or complete tests, fixtures, seams, fault injection, and registration.
5. `review`: review tests and minimum testability changes; only `PASS` permits a build.
6. `build`: build the exact candidate in the requirement-bound environment.
7. `execution`: execute the approved matrix and collect raw evidence.
8. `report`: append traceability, four-state results, metrics, cleanup, and residual risk to the run record.

## Checkpoint protocol

After every stage:

1. Update its state, summary, and evidence in the run manifest.
2. Append the relevant material to the requirement's test record.
3. Run the status command again.
4. Report what completed, where evidence lives, remaining gaps, and the next recommendation.
5. Stop for `PROCEED`, `REWORK`, or `STOP`.

Authorization to run a complete suite allows continuous execution only within an
already approved `execution` stage. It does not remove checkpoints between stages.

## Execution invariants

- Reuse existing test frameworks and build entrypoints before adding new ones.
- Test observable behavior; do not copy the implementation algorithm into assertions.
- Add only the smallest testability seam needed for time, randomness, I/O, IPC, or networking.
- Run fast unit tests before slower component and integration tests.
- Build and run ASan+UBSan separately from TSan. Any sanitizer finding is `FAIL`.
- Run performance tests only with an explicit scope, fixed environment and load,
  retained raw data, percentiles, and resource metrics.
- Use only `NOT_RUN`, `PASS`, `FAIL`, and `ENV_UNAVAILABLE` for test results.
- After failure, perform read-only diagnosis. Product fixes, rebuilds, and retests
  need a new decision; limit the same-root-cause cycle to three rounds.

## Environment and records

- Resolve and verify an environment profile before `intake`, then bind it to the
  requirement during `intake`.
- Reuse that binding for later runs without asking again; perform a read-only
  identity and health preflight each time.
- Ask before saving every newly discovered environment or fingerprint.
- Stop only when the environment is unavailable, drifted, lacks a required
  capability, or needs an unapproved mutation.
- Maintain one test record per requirement. Keep cases in a stable section and
  append every run as an immutable batch; never overwrite prior results.
- Bind each build and execution to the same candidate manifest hash, Git identity,
  environment binding, commands, receipts, and evidence.

## Final report

Include the candidate identity, requirement/risk traceability, environment binding,
exact commands, four-state results, first failure symptom, coverage, sanitizer and
performance results when applicable, evidence paths, cleanup verification,
uncovered risk, and recommendations.
