# Environment Profile discovery and persistence

Profiles are requirement-reusable, multi-node descriptions that contain only
protected references. Real addresses, private paths, access methods, and secrets
stay outside the public skill.

## Discovery and reuse

Check the manifest Profile reference, requirement test record, user-approved
private registry, then sanitized project registry. Do not search arbitrary home
or system directories. Reuse the requirement binding without asking again, but
run read-only fingerprint, health, capability, and credential-reference
preflight for every cycle.

If no Profile matches, ask only for stable binding/scope, participating nodes and
roles, platform/toolchain identity, capability entrypoints, evidence/cleanup,
and protected access, privilege, and datastore references. Never ask for secret
values to store in JSON.

## Multi-node model

Start from `assets/environment-profile.template.json`. Each build VM, test VM,
datastore host, GUI target, or other relevant node has its own:

- node ID, roles, platform identity, and fingerprint;
- protected access and optional privilege reference;
- named SSH/datastore/service credential references;
- capabilities and role-specific commands;
- read-only preflight and run-scoped cleanup commands.

Do not use one global Redis, SSH, or privilege alias for machines with different
authentication sources.

## Persistence decision

For an unknown environment or fingerprint, ask the user to choose:

- `PRIVATE`: reusable private Profile outside the public repository;
- `PROJECT`: sanitized, shareable Profile with protected references only;
- `SESSION`: current run only;
- keep the existing binding or stop.

Only write or replace a Profile after that decision. Installing dependencies,
changing configuration, restarting a shared node, or replacing a requirement
binding needs separate authorization.

## State and validation

Manifest states remain `UNCONFIGURED`, `CONFIGURED`, `VERIFIED`, `DRIFTED`, and
`UNAVAILABLE`. Only `VERIFIED` permits testing. A newly observed node or
fingerprint is drift until accepted and preflighted.

Profiles require UTF-8 structured JSON decision evidence and reject secret-like
fields and raw credential values. Validate before selection:

```bash
python scripts/environment_profile.py validate profile.json
```
