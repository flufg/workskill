# Private Build Recipe contract

The public Skill owns admission, transport, queueing, receipts, readback, and VM
state restoration. The private Build Recipe owns project-specific scope names and
the private provider that performs the actual remote build.

Use `assets/build-recipe.template.json` and keep the recipe beside its environment
Profile as `build-recipe.json`. Its provider reference must use
`provider:profile/...`; the referenced script is stored below the same Profile's
`providers/` directory, outside the public Skill.

Pin the provider's lowercase SHA-256 in `runner.expectedSha256`. Validation and
admission fail on any provider drift. After an intentional edit, review the exact
diff and update the pinned hash as its own explicit recipe change.

## Scope contract

Each scope declares:

- a stable lowercase identifier;
- a short description suitable for user selection;
- `execution: remote-non-gui`;
- the exact number of required artifact readback lines.

## Disposable workspace contract

A private provider may stage an externally synchronized or otherwise prepared
source tree into a disposable workspace. Keep every concrete path and source
mapping in the private recipe/provider, not in the public Skill.

- Validate the selected source before mutation. Never create, repair, retarget,
  or synchronize the source as an implicit part of the build.
- Restrict replacement to one exact provider-owned disposable path. Reject an
  empty, root, parent, source, or otherwise unexpected target before deletion.
- Recreate the disposable workspace before the admitted build/test and run all
  build/test commands there. Emit:

```text
==> WORKSPACE_READY source=<safe-logical-name> workspace=<exact-path>
```

- A separate preparation scope for test-only work is allowed and declares
  `expectedArtifactCount: 0`. A build scope may instead prepare the workspace
  internally before compiling.
- Preserve the workspace after build/test, including failures, until diagnosis
  and result review are complete. Never place automatic workspace deletion in a
  build or test success path.
- Cleanup is a separately declared remote, non-GUI scope with
  `expectedArtifactCount: 0`. Execute it only after the user accepts the result,
  ends the task, and then confirms cleanup immediately before execution.
- The cleanup implementation must revalidate the exact disposable path, delete
  only that path, prove it is absent, and emit:

```text
==> WORKSPACE_CLEANUP_READBACK path=<exact-path> absent=true
```

Result acceptance is not cleanup authorization. Never delete or modify the source
tree, its external synchronization, a shared cache, or another run's workspace.

The SSH adapter rejects undeclared scopes. The provider receives only the selected
scope as one quoted argument and is streamed to `bash -s`; it is not installed or
persisted on the guest by the public adapter.

Do not put GUI actions, credentials, deployment, Git operations, broad cleanup, or
hard power actions in a build provider. Do not use `eval`, interpolate untrusted
input into shell, silently select a broader scope, or fall back to another source
tree. Keep project roots, component mappings, toolchain quirks, and organization
procedures in the private provider rather than `SKILL.md` or public references.

## Artifact readback

After verifying a nonempty artifact, emit exactly:

```text
==> ARTIFACT_READBACK path=<no-whitespace-path> size=<bytes> sha256=<64-lowercase-hex> mtime=<epoch>
```

The public adapter parses those lines, compares their count to the selected scope,
and records the metadata in the audit. An exit code of zero without the required
readbacks fails.

The fictional `assets/providers/remote-build.sh` demonstrates artifact and
disposable-workspace protocols.
Replace it in a private candidate directory before using the Profile.

## Change invalidation

The recipe and provider are hashed for the run. Any change to the Profile, recipe,
provider, source manifest, candidate, dependency input, or symlink target after a
build invalidates that build evidence. Re-run the exact admitted scope with a new
receipt.
