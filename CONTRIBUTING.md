# Contributing

Contributions are welcome through issues and pull requests.

## Workflow

1. Fork the repository.
2. Create a focused branch from the latest `main`.
3. Make the smallest coherent change.
4. Run the validation commands below.
5. Open a pull request describing the behavior changed, evidence, and remaining risk.

Do not request or rely on direct pushes to `main`.

## Safety and privacy

Never commit:

- passwords, tokens, private keys, cookies, or credential values;
- private machine addresses, personal paths, or internal hostnames;
- organization-only build, VM, GUI, or datastore procedures;
- real environment profiles containing private infrastructure details;
- customer IPs, hostnames, account names, SSH details, Sunlogin/ToDesk device IDs,
  verification codes, temporary passwords, or internal paths;
- test or Bug logs, screenshots, core files, packet captures, collection bundles,
  reports, or fixtures containing confidential data.

Public environment profiles must be sanitized and keep only protected credential
references. Use obvious fictional values in templates and examples.

Changes to `SKILL.md`, executable scripts, environment handling, authorization
boundaries, or secret handling require especially careful review. Do not weaken
stage gates or turn a read-only helper into an automatically mutating operation.

## Validation

From `skills/linux-client-whitebox-test-flow` run:

```bash
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/environment_profile.py validate assets/environment-profile.template.json
python scripts/whitebox_flow.py validate assets/whitebox-run.template.json
python scripts/whitebox_flow.py status assets/whitebox-run.template.json
```

The unconfigured run template should stop at `environment_setup`. Add or update
tests for every behavior change.

For `skills/linux-client-bug-troubleshooter`, validate the skill metadata and
JSON evaluation cases, check all linked references, and scan the complete package
for credentials, customer identifiers, private addresses, and personal paths.
Changes to access-channel rules, collection scripts, or customer-data handling
must preserve the per-case authorization boundary and must not introduce a
persistent customer environment registry.

From `skills/build-client` run:

```bash
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/profile_manager.py validate \
  --environment assets/environment-profile.template.json \
  --recipe assets/build-recipe.template.json
```

Also scan the complete package for private keys, known-host entries, real machine
addresses, personal paths, internal component or artifact names, credential
values, and organization-only provider logic. Only fictional templates belong in
the public package. Real Profiles and provider scripts must stay outside the
repository.

For `skills/work-document-to-feishu`, validate `SKILL.md` frontmatter, parse
`evals/evals.json`, check that every linked reference exists, and confirm
`config/wiki-target.json` is not committed. Scan the package for real wiki
tokens, tenant hostnames, personal paths, and credential values. Templates may
only use placeholders such as `<SPACE_ID>` and `wikcnExampleParent`.

## License for contributions

By submitting a contribution, you agree that it is your original work or that
you have the right to submit it, and that it may be distributed under the
repository's [MIT License](LICENSE).
