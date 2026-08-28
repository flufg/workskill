# workskill

Reusable Codex skills for engineering workflows.

## Skills

- [`linux-client-whitebox-test-flow`](skills/linux-client-whitebox-test-flow/) — recoverable, auditable Linux client testing with supplemental cycles, release bundles, multi-node Profiles, and checkpointed or continuous authorization.

## Install a skill

Copy the complete skill directory into your Codex skills directory. Keep its
`SKILL.md`, `agents`, `assets`, `references`, and `scripts` directories together.

```bash
cp -R skills/linux-client-whitebox-test-flow "$CODEX_HOME/skills/"
```

The skill is environment-neutral. Bind project-specific build machines, test
VMs, credentials, commands, and GUI procedures in a private environment profile;
do not commit secrets to this repository.

On first use, the skill checks for a matching environment profile. If none exists,
it guides the user through configuration before testing. Newly discovered
environments are saved only after the user chooses private, project-shared, or
session-only persistence.

## Repository layout

```text
skills/      Installable skill packages
docs/        Human-oriented design and usage notes
```

## License

Licensed under the [MIT License](LICENSE). You may use, modify, and distribute
this project while preserving the copyright and license notice.

Contributions are welcome through pull requests. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting changes.
