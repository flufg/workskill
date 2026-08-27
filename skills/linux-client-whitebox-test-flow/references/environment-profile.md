# Requirement-level environment profile

Bind one build/test environment to a requirement during intake. Store only a
non-secret reference in the run manifest; keep machine addresses, credentials,
private paths, and organization-specific procedures in a private configuration.

The profile should define:

- stable binding ID and display name;
- build and test platform identities;
- build/test commands or capability references;
- toolchain and profile identifiers;
- supported coverage, sanitizer, performance, service, datastore, and GUI capabilities;
- artifact identity and evidence collection methods;
- protected credential resolution;
- namespace-scoped setup and cleanup;
- read-only health and drift checks.

Later runs for the same requirement reuse the binding without asking again.
Preflight it before every build or execution. Stop for a user decision only when
it is unavailable, drifted, missing a required capability, or needs an unapproved
mutation such as dependency installation, configuration change, restart, or
replacement.
