# Environment Profile discovery and persistence

The Profile is a reusable operation contract, not merely an SSH address. It binds
the local VMware controller and Linux guest to the same queue, VM identity,
endpoint, capability policy, timeouts, and evidence rules. Use
`assets/environment-profile.template.json` as the schema-v2 starting point.

## Discovery order

The Profile manager checks:

1. an explicit `--profile` path, which is session-scoped unless saved;
2. an explicit saved `--binding-id`;
3. the user-approved private registry under
   `$CODEX_HOME/profiles/build-client/` or `~/.codex/profiles/build-client/`;
4. the sanitized project registry under
   `<project>/.codex/profiles/build-client/` when `--project-root` is supplied.

It does not scan arbitrary home, system, SSH, VMware, or project directories.

```powershell
python '<skill-directory>\scripts\profile_manager.py' list --project-root '<project-root>'
python '<skill-directory>\scripts\profile_manager.py' resolve --binding-id '<binding-id>' --project-root '<project-root>'
```

Zero matches returns `UNCONFIGURED`. Multiple matches return `CHOICE_REQUIRED`.
The agent must ask the user instead of choosing or combining environments.

## Configure a candidate

Create an unregistered candidate directory:

```powershell
python '<skill-directory>\scripts\profile_manager.py' init '<candidate-directory>'
```

Ask only for stable, non-secret facts:

- binding name, scope, environment and node fingerprints;
- VMware executable and VMX locations, display name, guest OS, UUID, MAC, and
  expected guest address;
- SSH host, port, user, independently confirmed host-key fingerprint, and least
  capabilities;
- queue resource, timeouts, evidence location policy, and Build Recipe metadata;
- logical credential and provider references.

Never ask for a password, private key body, token, or passphrase in chat or JSON.
The SSH key and managed known-host file are resolved in per-user Codex state under
`$CODEX_HOME/state/build-client/`, keyed by the binding and fingerprint; they are
never written into a project Profile. A private build provider is resolved beneath
the Profile's `providers/` directory.

Validate before selection or persistence:

```powershell
python '<skill-directory>\scripts\profile_manager.py' validate --environment '<candidate-directory>\environment.json' --recipe '<candidate-directory>\build-recipe.json'
```

## Persistence decision

For an unknown user-supplied environment, ask the user to choose:

- `PRIVATE`: save reusable concrete infrastructure outside the repository;
- `PROJECT`: save only when both files are explicitly marked `shareable=true` and
  all values and the provider are sanitized for project sharing;
- `SESSION`: use the explicit candidate files for this run without copying them;
- stop without using the environment.

```powershell
python '<skill-directory>\scripts\profile_manager.py' save --environment '<candidate>\environment.json' --recipe '<candidate>\build-recipe.json' --mode PRIVATE
```

Saving never accepts embedded secrets. Existing bindings are not overwritten
without explicit replacement authorization. If the fingerprint differs, ordinary
replacement still fails; explicit fingerprint-change acceptance is additionally
required after the user verifies that this is an intentional environment change.

Host-key, VMX UUID/MAC, machine-ID, endpoint, or fingerprint drift in a previously
saved binding is a security failure, not automatic discovery of a new environment.
Stop, preserve the previous Profile, and ask the user whether to create a separate
binding, explicitly replace the old binding, or investigate.

## States

- `UNCONFIGURED`: no valid matching Profile and recipe.
- `CONFIGURED`: files validate locally, but target preflight is outstanding.
- `VERIFIED`: exact VMX, host key, machine ID, provider, capability, and health
  preflight passed for the current run.
- `DRIFTED`: a bound identity or fingerprint changed.
- `UNAVAILABLE`: the exact target cannot currently be verified or reached.

Only `VERIFIED` permits a build or test. Verification is fresh run evidence; it is
not silently persisted as permanent authorization.
