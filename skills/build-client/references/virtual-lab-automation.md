# Virtual lab automation contract

This contract governs a Linux guest reached through local VMware Workstation for
power and direct console access, plus SSH for non-GUI guest operations. It does
not authorize a connection, mutation, build, test, power action, or snapshot.

## Identity and capability model

The Profile must bind:

- one local VMware provider and one Linux SSH provider;
- the same queue resource, VM identity, and expected guest endpoint;
- VMX path, display name, guest OS, UUID, and MAC;
- managed SSH host-key fingerprint and hashed guest machine ID;
- separate least-privilege capability lists;
- bounded timeouts and receipt lifetime.

VMware may expose status, start, direct GUI console, soft stop, and soft restart.
SSH may expose read, execute, and explicitly approved copy. Hard stop, snapshots,
guest reboot/power, and GUI launch over SSH remain forbidden.

## Read-only release gates

Before first use or every resumed run, verify:

1. configuration and recipe validity;
2. protected credential/provider references exist;
3. VMX and managed host-key identity match exactly;
4. a bounded read-only connection returns complete OS, kernel, architecture,
   uptime, memory, filesystem, hostname, and machine-ID evidence;
5. declared capabilities match this paired access mode.

The first connection proves identity and connectivity only.

## Side-effect gate

Every build, process launch, test mutation, service change, artifact move, or
cleanup follows:

1. selected Profile status;
2. VMX and host-key match;
3. exclusive host queue claim;
4. exact target identity after the claim;
5. bounded preflight and fresh receipt;
6. action, artifact/target readback, identity readback, audit, then queue release.

The host claim covers VM start, SSH readiness, the remote exclusive lock, action,
readback, and restoration of the original power state. Never infer that an old
claim is safe to delete, steal another owner, or release a mismatched run ID.

If `vmrun` reports stopped while the selected SSH endpoint is reachable, treat the
Windows execution context as ambiguous and perform no power action. If a stopped
VM must be started for an admitted action, use `nogui`; soft-stop it only when this
run started it. Never use a hard fallback.

## Receipts and copies

A fresh receipt binds run ID, Profile and recipe hashes, queue owner, host key,
machine identity, capabilities, preflight, issue time, and maximum age. Consume it
for one side effect. Reboot, snapshot restore, environment rebuild, identity
change, provider change, or product cleanup invalidates earlier readiness.

Copy capability is not synchronization permission. Require exact direction,
source/destination, overwrite policy, size/count bounds, hashes, candidate/source
manifest binding, and destination readback. Reject broad roots, unresolved globs,
credentials, symlink drift, and changes to sealed build inputs.

Git hosting owns candidate selection, protected refs, review, pipeline, and
release approval. This Skill owns target identity, queue, preflight, action, and
environment evidence. Neither gate replaces the other.
