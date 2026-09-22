# Build-client testing workflow

Use this workflow only after an explicit request to test, verify, benchmark,
smoke-test, or accept a selected target. Read
[virtual-lab-automation.md](virtual-lab-automation.md) first. For GUI work also
read [gui-testing.md](gui-testing.md); for Redis writes also read
[redis-test-injection.md](redis-test-injection.md).

## Resolve scope and record

Resolve exactly one environment Profile and one Build Recipe. Use only scopes and
artifacts declared by that recipe. If the target component, test type, pass
threshold, environment, or required capability cannot be determined safely, ask
the user; do not default to every component or production load.

When the request context identifies exactly one writable test record, write the
test case before execution and append the result afterward. If it identifies none
or several, ask the user before choosing or creating a record. Keep routine build
output separate from the test result.

## Read-only prerequisites

Check the applicable language/framework, source and candidate identity,
dependencies, selected recipe/provider, artifact, services, ports, fixtures,
monitoring access, cleanup plan, and measurable pass criteria. Do not install,
repair, restart, or mutate anything merely because a prerequisite is missing.

Run the offline Profile check and read-only SSH check. Require exact VMX, host key,
machine ID, capability, `exitCode=0`, `timedOut=false`, and complete readback. Do
not claim a queue merely to present available scopes or test choices.

## Execute one selected test

Before the side effect, present the exact selected test, expected outcome,
measurable pass criteria, bounded command or direct-console action, fixture and
cleanup plan. Performance work requires explicit confirmation of the target and
load bounds.

When the selected private provider uses a disposable workspace, resolve exactly
one declared source mapping, recreate only the exact disposable workspace, and
run every build/test command there. Treat the source and its synchronization as
read-only external inputs. Preserve the workspace through failures, diagnosis,
retries, and user review.

Claim the shared queue, read identity again, issue a fresh receipt, execute only
the admitted action, verify target/artifact state, verify cleanup, read identity
again, write evidence, then release the queue. An accepted command, existing
artifact, running PID, or opened window is not a pass.

Use only `NOT_RUN`, `PASS`, `FAIL`, and `ENV_UNAVAILABLE`. Capture timestamps,
Profile/recipe/provider hashes, queue owner and release state, receipt, identity,
exit and timeout state, decisive output/screenshots, artifact hashes, metrics,
cleanup readback, and uncovered risk.

After the user accepts the result and ends the test task, ask again immediately
before invoking the separately declared cleanup scope. Record its exact-path
guard and `WORKSPACE_CLEANUP_READBACK ... absent=true`. Do not infer cleanup
authorization from the original test request, a passing result, acceptance, or
the presence of an old workspace.

## Failure handling

Perform read-only diagnosis first: isolate the failed criterion, rank likely
causes with evidence, and run at most a small number of safe verification reads.
Product fixes, dependency/configuration changes, fixture mutation, rebuild, or
retest require authorization unless the original request explicitly included
them. Stop after three failed repair-and-retry rounds for the same root cause.

The final report identifies the exact candidate, environment, recipe scope,
evidence, result, cleanup state, remaining risk, and next decision. It never
pushes or publishes code.
