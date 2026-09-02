# Redis test-data injection

Use this contract only when an explicitly selected test requires Redis writes. A
general build or test request does not authorize unspecified Redis mutation.

## Protected credential

Read the Redis credential reference from the selected environment Profile. Never
use a hardcoded alias. Check only its existence:

```powershell
python '<skill-directory>\scripts\redis_credential.py' --reference '<credential-reference>' status
```

When absent, ask the user to run the no-echo setup in the same interactive Windows
desktop session:

```powershell
python '<skill-directory>\scripts\redis_credential.py' --reference '<credential-reference>' setup
```

Rotate only after explicit approval with `setup --replace`. Delete only with an
exact matching `--confirm-reference`. The adapter has no get, show, print, or
export command.

At execution time, import `read_secret(reference)` and keep the value in memory.
Pass it through private stdin or an equivalent in-memory channel. Never put it in
arguments, URIs, environment variables, temporary files, shell history, logs,
receipts, evidence, or chat.

## Exact test plan

Before connecting, require the exact endpoint or absolute Unix socket, auth mode,
database, key names, Redis types, operations, value encodings and hashes, finite
TTLs, unique run namespace, scalar limits, readback criteria, and cleanup for only
the keys created by this run.

Permit connection setup and only the exact data commands admitted by the test
plan. Reject server-wide administration, flushes, wildcard cleanup, configuration,
module, shutdown, replication, migration, restore, scripting/eval, ACL changes,
unbounded scans, and unbounded writes.

Follow the shared Profile identity, queue, preflight, fresh receipt, bounded
mutation, readback, test, exact cleanup, absence verification, final identity, and
queue-release sequence. Authentication failure, endpoint drift, key collision,
wrong type, missing TTL, readback mismatch, timeout, or cleanup mismatch fails
closed. Never print or silently replace a rejected credential.
