# White-box testing workflow

## Principle

Automation means detecting progress, executing the current authorized stage, and
collecting evidence. It does not cross a user decision gate. On resume, accept
only readable evidence tied to the current candidate and environment binding.

## 1. Intake

Record the requirement, repository and Git ref, component, change type, candidate
manifest SHA-256, optional commit, objectives, exclusions, constraints, test-record
location, and requirement-level environment binding.

Complete when the candidate, record, scope, and environment are uniquely identified.

## 2. Discovery

Read the requirement, diff, implementation, and interfaces. Locate tests, fixtures,
fakes, build files, and CI entrypoints. Identify boundaries such as filesystem,
network, IPC, database/cache, service manager, kernel, GUI, time, randomness,
threads, and processes. Map high-risk paths including permission failures, timeouts,
retries, partial I/O, concurrency, cancellation, crash recovery, and cleanup.

Do not start a build during discovery.

## 3. Plan

Create a matrix with these fields:

| Field | Meaning |
|---|---|
| requirement | Requirement or defect item |
| risk | Failure mode and impact |
| layer | unit/component/integration/system/performance |
| case | Input, action, expected behavior |
| observability | Return value, state, log, event, file, or metric |
| command | Reproducible command or planned entrypoint |
| pass criteria | Explicit success condition |
| cleanup | Temporary resources and rollback |

Cover normal, boundary, failure, recovery, concurrency, and lifecycle behavior.
Specify coverage reporting, independent sanitizer variants, optional performance
method, environment capabilities, and read-only diagnostic evidence. Every high
risk needs an executable test or a justified gap.

## 4. Test assets

Reuse the repository's framework. Implement small deterministic tests, isolated
temporary resources, dynamic ports, explicit process cleanup, and minimal seams.
Inject relevant failures such as interruption, would-block, no-space, denied access,
timeout, or partial I/O. Register tests with existing build/test entrypoints and
perform safe local checks.

Record product defects instead of silently changing product semantics.

## 5. Review

Review whether assertions observe public behavior, tests duplicate product logic,
mocks or seams are excessive, concurrency and cleanup are deterministic, fault
injection reaches the intended path, registration and commands are correct, and
logs could expose secrets. Record `PASS` or `FAIL`; unresolved blockers return to
`test_assets`.

## 6. Build

Pass the candidate identity, build scope, change type, required test/sanitizer
variants, expected artifacts, environment binding, and planned test commands to
the selected build capability. The receipt must identify environment, source,
commands, exit code, artifact hashes, and logs. Stop on build failure.

## 7. Execution

Within one approved execution stage:

1. Preflight candidate artifact and environment identity.
2. Run fast unit tests.
3. Run component and integration tests.
4. Generate coverage evidence.
5. Run ASan+UBSan independently.
6. Run TSan independently.
7. Run applicable fault, concurrency, lifecycle, and leak tests.
8. Run authorized performance, stress, capacity, or endurance tests.
9. Run applicable service, datastore, or GUI scenarios through the bound profile.
10. Clean up and verify cleanup by reading state back.

Record the first failure symptom and raw evidence. Do not automatically fix,
rebuild, or retest.

## 8. Report

Append the candidate, environment, traceability matrix, exact commands, timestamps,
exit codes, results, coverage, sanitizer output, performance data, screenshots,
cleanup, gaps, and residual risks to the current run batch. Do not overwrite older
batches or automatically publish code.

## Failure branches

- `FAIL`: collect read-only evidence and offer fix/retest, adjust test, accept and report, or stop.
- `ENV_UNAVAILABLE`: record the missing capability and recovery action; it is neither product failure nor pass.
- Limit the same-root-cause repair/retry loop to three user-authorized rounds.
- A candidate change invalidates affected build/execution evidence and restarts from the earliest affected stage.
