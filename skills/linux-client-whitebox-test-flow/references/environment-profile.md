# Environment profile discovery and persistence

An environment profile is required before the eight testing stages start. The
public skill contains only the schema and decision rules; real addresses, private
paths, access methods, and organization-specific procedures stay outside it.

## Discovery order

Check, in order:

1. `environment.profileRef` in the current run manifest;
2. the environment binding recorded in the requirement's test record;
3. a user-configured private registry, conventionally
   `$CODEX_HOME/environment-profiles/` when available;
4. a project registry such as `.codex/environment-profiles/` containing only
   sanitized, shareable profiles.

Do not search arbitrary home or system directories. A matching profile must be
readable and its expected fingerprint must match the observed environment.

## Missing profile interview

If no profile matches, stop before `intake` and ask only for information that
cannot be discovered safely:

- stable name and intended scope;
- build and test platform identities and access method;
- toolchain/profile identifiers;
- build/test commands or capability providers;
- coverage, sanitizer, performance, service, datastore, and GUI capabilities;
- artifact identity and evidence collection;
- namespace-scoped setup and cleanup;
- read-only health and drift checks;
- protected credential references, never secret values.

Create the minimum profile that supports the approved scope, then perform a
read-only preflight.

## Save decision for a new environment

Whenever an unknown environment or new fingerprint is observed, ask the user to
choose one of these outcomes before writing it anywhere:

- `PRIVATE`: persist in a user-approved private registry for later requirements;
- `PROJECT`: persist a sanitized profile in the project for team reuse;
- `SESSION`: reference it only in the current run and do not persist it;
- keep the existing binding or stop.

For `PROJECT`, reject secret values, private keys, tokens, passwords, private
machine addresses, and organization-only paths. Store protected credential aliases
or provider references instead. For `PRIVATE`, secrets should still remain in a
credential manager; the profile stores only references.

## State and fingerprint

The manifest uses these states:

- `UNCONFIGURED`: no usable profile has been selected; ask the user to configure one.
- `CONFIGURED`: a profile was selected or created but has not passed preflight.
- `VERIFIED`: observed fingerprint matches and required capabilities are available.
- `DRIFTED`: observed identity differs from the profile; ask how to handle the new environment.
- `UNAVAILABLE`: the profile cannot currently provide the required environment.

Only `VERIFIED` permits `intake`. Later runs reuse the requirement binding without
asking again, but always repeat the read-only preflight. Installing dependencies,
changing configuration, restarting a shared environment, or replacing the binding
requires separate authorization.

Start new profiles from `assets/environment-profile.template.json`.

For JSON profiles, run this structural and secret-flag gate before selecting the
profile:

```bash
python scripts/environment_profile.py validate profile.json
```

This validator is read-only. It rejects incomplete profiles and any profile that
declares `containsSecrets: true`; it cannot replace an external secret scanner.
