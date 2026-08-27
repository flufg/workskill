# Quality gates and evidence

## General gates

Every completed stage needs a non-empty summary and at least one readable evidence
reference. The next stage additionally requires the previous stage to be
`COMPLETED`, an explicit `PROCEED`, an unchanged candidate identity, and its
specialized prerequisite.

No testing stage may start until the environment state is `VERIFIED`. Missing,
unavailable, or drifted profiles stop before `intake`; a configured but unverified
profile must complete a read-only preflight first.

`REWORK` stays at the current checkpoint. `STOP` ends the run.

| Next stage | Required condition |
|---|---|
| intake | environment profile is `VERIFIED` |
| discovery | intake uniquely identifies candidate, record, and environment |
| plan | risks and existing test/build capabilities are evidenced |
| test_assets | traceability, commands, pass criteria, and cleanup are approved |
| review | test assets are implemented and registered |
| build | review decision is `PASS` |
| execution | build is `PASS` and artifact/environment identities match |
| report | execution has terminal results and raw evidence |

## Four result states

- `NOT_RUN`: not executed; never report it as pass.
- `PASS`: command, assertions, metrics, and evidence satisfy the pass criteria.
- `FAIL`: behavior, assertion, sanitizer, performance gate, or cleanup failed.
- `ENV_UNAVAILABLE`: a required environment capability is absent; neither pass nor product failure.

## Minimum applicability review

Check whether each category applies: core unit logic, invalid/boundary inputs,
filesystem/network/IPC/datastore failure injection, concurrency and cancellation,
start/stop and repeated lifecycle, component/integration paths, coverage,
ASan+UBSan, TSan, performance/stress/capacity/endurance, and GUI behavior. Record
why an omitted category is not applicable.

## Safety gates

- Resolve credentials only through the target environment's protected mechanism;
  never put secret values in manifests, commands, logs, or reports.
- Scope injected data and cleanup to the current run namespace and verify cleanup.
- Follow the bound profile for GUI sessions; do not invent remote GUI launch methods.
- Do not install dependencies, mutate shared configuration, restart environments,
  fix product code, publish, or push without separate authorization.

## Minimum evidence

- Candidate source-manifest SHA-256 and Git identity.
- Requirement/risk/test matrix and test-record batch ID.
- Review decision.
- Environment binding, preflight, build receipt, and artifact hashes.
- Exact commands, working directory, timestamps, exit codes, and test logs.
- Coverage, sanitizer output, performance data, screenshots, and cleanup readback when applicable.
