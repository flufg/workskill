---
name: build-client
description: On explicit user instruction, discover or configure a non-secret paired VMware Workstation and Linux SSH Profile, safely manage VM power, and run an exact private build recipe with queue, identity, receipt, artifact, and power-state evidence. Not for implicit builds, Git publishing, deployment, hard power, or snapshots.
---

# Build Client

Operate a Linux build guest through one reusable environment Profile and one
private Build Recipe. The public Skill contains no real address, personal path,
machine identity, credential, product artifact, or organization-only build
procedure.

## Authorization boundary

Require an explicit user request naming a build, test, verification, or VM power
action. A code change, requirement discussion, stale artifact, or earlier build
does not authorize another action.

Build and test authorization never authorizes commit, amend, rebase, tag, push,
release, deployment, hard stop, snapshot, unrelated restart, dependency install,
configuration repair, or disposal of a retained build/test workspace. Ask again
immediately before any later Git push or workspace cleanup.

A build may start a stopped VM only for the requested action and must restore the
original stopped state with a verified soft shutdown. Leave an initially running
VM running.

## Resolve the environment before connecting

Read [references/environment-profile.md](references/environment-profile.md),
then resolve the Profile without network access:

```powershell
python '<skill-directory>\scripts\profile_manager.py' resolve --project-root '<project-root>'
```

- `UNCONFIGURED`: ask only for non-secret environment and recipe information,
  scaffold a candidate, validate it, then ask the user to choose `PRIVATE`,
  `PROJECT`, or `SESSION`. Never choose persistence silently.
- `CHOICE_REQUIRED`: show safe Profile names and scopes, then ask the user to
  select exactly one.
- One match: reuse it without asking again, but run read-only identity, health,
  capability, credential-reference, and recipe-provider preflight every time.
- New user-supplied environment: validate it, then ask whether to save it.
- Changed host key, VM identity, machine ID, endpoint, or fingerprint: mark it as
  drift and stop. Never reinterpret drift as a new environment or replace the
  saved binding without explicit acceptance.

Profiles store only protected/provider/session references. Passwords, private-key
bodies, tokens, and passphrases must never appear in chat, JSON, commands, logs,
receipts, reports, or repository files. Interactive setup accepts secrets only
through no-echo prompts.

## Select the operation

Read the resolved recipe's `scopes`. Build exactly one named scope unless the user
explicitly requests a declared aggregate scope. Do not invent a scope, infer a
full build from `all`, or fall back to another recipe/provider.

The private provider must be referenced by `provider:profile/...`, execute without
a GUI, and emit one verified line per artifact:

```text
==> ARTIFACT_READBACK path=<path> size=<bytes> sha256=<64-hex> mtime=<epoch>
```

The expected count comes from the selected scope. Missing artifact evidence is a
failed build even when the command exits successfully.

When the private recipe/provider uses a disposable workspace, keep concrete
source and workspace paths private. Recreate only the provider's exact disposable
workspace before the admitted build/test, never mutate its source tree, and keep
the workspace after execution for diagnosis and result review. Cleanup must be a
separately declared zero-artifact scope. A successful test, result acceptance, or
request to end the task does not authorize cleanup: obtain a separate immediate
confirmation, require exact-path and absence checks in the provider, and capture
the cleanup readback. See
[references/build-recipe.md](references/build-recipe.md).

For build-only requests, read
[references/build-recipe.md](references/build-recipe.md) and
[references/virtual-lab-automation.md](references/virtual-lab-automation.md).
For any test, coverage, performance, smoke, or acceptance request, also read
[references/testing-workflow.md](references/testing-workflow.md). For a graphical
test, also read [references/gui-testing.md](references/gui-testing.md). For Redis
test-data injection, also read
[references/redis-test-injection.md](references/redis-test-injection.md).

## Paired VMware and SSH contract

The selected Profile must contain exactly one local `vmware-workstation` provider
and one Linux `ssh` provider. They must share the exact `queueResource`,
`vmIdentity`, and guest endpoint.

- VMware owns status, start, direct GUI console, soft stop, and soft restart.
- SSH owns read, execute, and explicitly approved copy operations.
- Hard power, snapshots, guest power, guest reboot, and GUI launch through SSH are
  forbidden.
- The first read-only connection proves identity and connectivity only; it does
  not authorize a build, test, process launch, service change, or cleanup.
- Any Profile, host-key, VMX, machine-ID, queue, receipt, timeout, provider, or
  readback failure is fail-closed.

Run VMware commands in the Windows logon session that owns Workstation. If
`vmrun` reports the VM stopped while the selected SSH endpoint is reachable, stop
because the execution context is ambiguous.

## Setup and readiness

Validate the selected environment, recipe, local VMX identity, references, and
provider before any connection:

```powershell
python '<skill-directory>\scripts\vmware-client.py' --binding-id '<binding-id>' --project-root '<project-root>' profile-check
```

If the dedicated SSH key or managed known-host file is absent, ask the user to run
the one-time interactive setup:

```powershell
python '<skill-directory>\scripts\remote-client.py' --binding-id '<binding-id>' --project-root '<project-root>' setup
```

The expected SSH host-key fingerprint must already be confirmed out of band.
Setup may generate a dedicated key under the private Profile directory and install
its public key, but must never accept a password argument or environment variable.

If the machine ID is not pinned, obtain explicit initialization authorization:

```powershell
python '<skill-directory>\scripts\vmware-client.py' --binding-id '<binding-id>' --project-root '<project-root>' vm-init --pin-machine-id
```

Initialization may start the VM with `nogui`, verify the pinned VMX and SSH
identity, record the machine-ID hash, then restore the original power state with a
soft stop. It never replaces an existing different machine ID.

Use the read-only first-contact check when connectivity evidence is needed:

```powershell
python '<skill-directory>\scripts\remote-client.py' --binding-id '<binding-id>' --project-root '<project-root>' check
```

Continue only on exact host-key and machine identity, `exitCode=0`,
`timedOut=false`, and `selectedProfileReady=true`.

## Execute

Immediately before a remote side effect, reconfirm the explicit action and run:

```powershell
python '<skill-directory>\scripts\vmware-client.py' --binding-id '<binding-id>' --project-root '<project-root>' vm-build '<declared-scope>'
```

The adapter holds the host lifecycle queue across power-on, SSH readiness, the
remote queue and fresh receipt, provider execution, artifact and identity
readback, and restoration of the original power state. Never steal a queue, delete
an unreadable claim, weaken host-key checking, reuse a stale receipt, or infer
success from stdout or an existing artifact.

Standalone `vm-start`, `vm-stop`, `vm-restart`, and initialization still require
an explicit request naming that operation. `vm-stop` is soft only; restart is
soft-stop, verified stopped, start, then exact SSH identity readback.

## Candidate and evidence boundary

When invoked from a managed development workflow, require a sealed candidate
commit. Bind candidate SHA and any approved source-manifest SHA-256 to the external
test/build record. A source, dependency, symlink target, recipe, provider, Profile,
or candidate change invalidates earlier evidence.

Report the selected binding and scope, environment/recipe/provider hashes, receipt
hash, both queue release states, artifact hashes, test result when applicable, and
final VM power state. Stop without pushing.
