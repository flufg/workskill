# workskill

Reusable Codex skills for engineering workflows.

## Skills

- [`linux-client-whitebox-test-flow`](skills/linux-client-whitebox-test-flow/) — recoverable, auditable Linux client testing with supplemental cycles, release bundles, multi-node Profiles, and checkpointed or continuous authorization.
- [`linux-client-bug-troubleshooter`](skills/linux-client-bug-troubleshooter/) — evidence-driven Linux client diagnosis from descriptions, screenshots, logs, SSH, or an authorized remote desktop session; produces engineer-facing material checklists, bounded collection scripts, decision-ready solutions, and Bug reports without modifying product code.
- [`build-client`](skills/build-client/) — explicit-only VMware Workstation and Linux SSH build/test execution with discoverable private, project, or session Profiles; keeps concrete infrastructure and organization build providers outside the public skill.

## Install a skill

Copy the complete skill directory into your Codex skills directory. Keep its
`SKILL.md` and all included resource directories together.

```bash
cp -R skills/<skill-name> "$CODEX_HOME/skills/"
```

Each skill documents its own environment boundary:

- `linux-client-whitebox-test-flow` uses private or sanitized environment Profiles
  for repeatable test infrastructure.
- `linux-client-bug-troubleshooter` never persists customer environments or access
  credentials. SSH, Sunlogin, and ToDesk access is limited to the currently
  authorized case session; missing evidence becomes a checklist for the engineer
  to coordinate with the customer.
- `build-client` discovers saved environment Profiles, asks before persisting a
  newly supplied environment, and treats identity drift as a hard stop rather
  than silently replacing the binding.

Never commit secrets, customer access details, diagnostic evidence, or private
infrastructure data to this repository.

## Repository layout

```text
skills/      Installable skill packages
docs/        Human-oriented design and usage notes
```

## Design notes

- [Linux client white-box test flow](docs/linux-client-whitebox-test-flow.md)
- [Linux client Bug troubleshooting](docs/linux-client-bug-troubleshooter.md)
- [Build client](docs/build-client.md)

## License

Licensed under the [MIT License](LICENSE). You may use, modify, and distribute
this project while preserving the copyright and license notice.

Contributions are welcome through pull requests. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) before submitting changes.
