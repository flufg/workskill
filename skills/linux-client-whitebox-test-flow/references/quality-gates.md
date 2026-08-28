# Quality gates and evidence

## General gates

Every completed stage needs a summary and evidence IDs present in the evidence
index. Testing requires a `VERIFIED` environment and release bundle. A transition
needs either stage-specific `PROCEED` or a matching `CONTINUOUS` grant.

`CONTINUOUS` must pause on failure, candidate change, environment drift,
destructive action, missing permission, unavailable credential, cleanup failure,
or scope expansion. It does not authorize those actions.

| Next stage | Required condition |
|---|---|
| intake | Profile and complete release bundle are `VERIFIED` |
| discovery | requirement, record, bundle, environment, and authorization are unique |
| plan | risks, component contracts, and capabilities are evidenced |
| test_assets | traceability, compatibility, commands, criteria, and cleanup are approved |
| review | test assets and fixtures are implemented and registered |
| build | review decision is `PASS` |
| execution | complete bundle build is `PASS`; artifact/node identities match |
| report | terminal cycle results, cleanup readback, and raw evidence exist |
| close | audit covers every completed cycle and report/test-record revision |

## Result and cause model

- `NOT_RUN`: not executed and carries a reason.
- `PASS`: command, assertions, metrics, and evidence satisfy criteria.
- `FAIL`: behavior, sanitizer, performance, fixture, compatibility, or cleanup failed.
- `ENV_UNAVAILABLE`: required environment capability is absent.

For `FAIL` and `ENV_UNAVAILABLE`, add one `reasonCategory`: `PRODUCT`,
`COMPATIBILITY`, `FIXTURE`, `INFRA`, or `ENVIRONMENT`. Domain-specific
observations remain separate annotations and never replace the four-state result.

## Compatibility gate

When a value crosses a version boundary through IPC, persistence, a datastore,
package metadata, or a service protocol, cover old/old, old/new, new/old, and
new/new. Unknown-value behavior must be explicit. Missing any combination blocks
the plan gate unless a documented exception is approved.

## Safety gates

- Resolve credentials on the target node through protected references. Never put
  secret values in profiles, manifests, commands, evidence, or reports.
- Scope injection and cleanup to the run namespace and verify cleanup by readback.
- Follow each node Profile for GUI, privilege, datastore, and access methods.
- A destructive fixture needs separate authorization, a recoverable baseline,
  the smallest isolated target, an explicit rollback plan, and recovery proof.
- Do not install, change shared configuration, restart, fix product code,
  publish, or push without separate authorization.

## Evidence gate

Index evidence with a stable ID. Local files require SHA-256; remote receipts
require a verification timestamp and `VALID`, `STALE`, or `UNAVAILABLE` status.
Prefer UTF-8 JSON decisions under a known
locale. Every cycle records exact commands, node and bundle identities,
timestamps, exit codes, results, logs, and cleanup. Every report revision records
covered cycle IDs, a unique test-record batch ID, and record evidence. A hashed
`RECORD_INDEX` sidecar mirrors the requirement document's revision/batch/cycle
coverage so audit can detect drift in either direction.

Run `audit` before report and close. Hash mismatch, missing local evidence,
unreported completed cycles, or cleanup failure blocks completion. Remote
evidence warnings require external revalidation before formal close.
