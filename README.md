# workskill

Reusable Codex skills for engineering workflows.

## Skills

- [`linux-client-whitebox-test-flow`](skills/linux-client-whitebox-test-flow/) — auditable, checkpointed white-box testing for Linux client changes.

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

No license has been selected yet. Until one is added, normal copyright rules
apply even though the repository is public.
