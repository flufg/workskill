# White-box testing workflow

## Principle

Automation detects recorded progress, executes authorized work, and appends
evidence. The requirement ledger is durable across initial execution, retest, and
supplemental cycles. Never rewrite a prior cycle to make the current state look
cleaner.

## Prerequisites

Before `intake`:

1. Resolve the requirement's saved Profile or configure one using
   [environment-profile.md](environment-profile.md).
2. Run read-only preflight on every participating node and require environment
   state `VERIFIED`.
3. Resolve every component in the release bundle and require bundle state
   `VERIFIED`.
4. Record `CHECKPOINTED` or an explicit, scoped `CONTINUOUS` grant.

If a Profile, fingerprint, node, credential reference, or component is new, stop
for the relevant user decision. Do not silently persist or substitute it.

## Initial cycle

### 1. Intake

Record the requirement, repository and Git ref, primary component, full release
bundle, objectives, exclusions, constraints, test-record location, environment
nodes, and authorization mode. Complete only when the bundle, record, scope, and
environment are uniquely identified.

### 2. Discovery

Read the requirement, diff, implementation, and interfaces. Locate tests,
fixtures, build files, CI, package producers, and consumers. Identify filesystem,
network, IPC, datastore, service, kernel, GUI, time, thread, and process
boundaries. For any contract or persisted value changed across versions, mark
compatibility as applicable.

### 3. Plan

Create a requirement-risk-test matrix with case ID, layer, input/action, expected
behavior, observability, command, pass criteria, cleanup, environment node, and
release components. Cover normal, boundary, failure, recovery, concurrency, and
lifecycle behavior.

When compatibility applies, generate the four producer-consumer combinations:
old/old, old/new, new/old, and new/new. Every high risk needs an executable case
or a justified gap. Domain-specific procedures belong to separately selected
specialist capabilities; this flow records their scope, authorization, results,
and evidence without embedding their mechanics.

### 4. Test assets

Reuse the repository framework. Implement deterministic tests, isolated run
namespaces, dynamic resources, explicit cleanup, and minimal seams. Validate
package fixtures before deployment. Record product defects instead of silently
changing semantics.

### 5. Review

Review public-behavior assertions, fixture validity, compatibility coverage,
registration, deterministic cleanup, fault-injection reachability, credential
protection, and evidence encoding. Only `PASS` permits build.

### 6. Build

Pass the release bundle, build scope, environment nodes, variants, expected
artifacts, and commands to the build capability. The receipt identifies every
component, source/artifact hash, environment, command, exit code, and log. Stop
on partial or mismatched bundles.

### 7. Execution

Append an `INITIAL` cycle before the first command. Bind it to bundle ID,
environment binding/fingerprint, and reason. Within the authorized stage:

1. Verify component artifacts and node identities.
2. Run fast tests, then component/integration and compatibility cases.
3. Generate coverage and independent sanitizer evidence.
4. Run applicable fault, lifecycle, performance, service, datastore, GUI, or other approved specialist cases.
5. Record structured results, first symptoms, and reason categories.
6. Perform exact cleanup and read state back.

Do not automatically fix, rebuild, mutate fixtures, or retest after a failure.

### 8. Report

Update the structured test-record index, run `audit`, then append a report
revision covering every completed unreported cycle. Append the same revision and
batch ID to the requirement test record and its index.
Set lifecycle to `REPORTED`; do not mark the ledger `CLOSED` merely because a
report exists.

## Reopen, retest, and supplement

After a report, authorized additional testing does not repeat intake through
review unless the affected scope, product/test assets, environment, or release
bundle changed.

1. Set lifecycle `REOPENED`, increment revision, and record the reason.
2. Append `RETEST` for a repeated case after an authorized correction, or
   `SUPPLEMENTAL` for newly added coverage.
3. Execute only the affected matrix against the bound bundle and environment.
4. Audit, append a new report revision, and update the test record.
5. Return to `REPORTED` or explicitly close.

A changed bundle moves the prior verified snapshot to `releaseBundleHistory` and
invalidates its evidence only for current conclusions; it never deletes the old
bundle or cycles. Restart from the earliest affected stage and bind every new
pending/active cycle to the current bundle.

## Failure and pause branches

- `FAIL`: classify as product, compatibility, fixture, infrastructure, or
  environment; collect read-only evidence and request a decision.
- `ENV_UNAVAILABLE`: record missing capability and recovery evidence; it is not pass.
- Cleanup failure: set cycle result `FAIL`, keep `cleanupVerified=false`, and stop.
- Environment or bundle drift: stop before any further command.
- Limit one root-cause repair/retry loop to three authorized rounds.

## Close

Set lifecycle `CLOSED` only after audit proves that all completed cycles are
covered by report revisions, test-record batch evidence exists, local hashes
match, remote receipts have current verification records, and cleanup succeeded.
