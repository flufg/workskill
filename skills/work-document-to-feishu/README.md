# Work document to Feishu

Review a work document, rewrite it as a professional plan or report, then archive it to a bound Feishu wiki.

Install the complete directory:

```bash
cp -R skills/work-document-to-feishu "$CODEX_HOME/skills/"
```

Cursor uses `~/.cursor/skills/` instead of `$CODEX_HOME/skills`. Keep `SKILL.md` together with `references/`, `evals/`, `agents/`, and `config/`.

Runtime wiki binding is written to `config/wiki-target.json` and must stay local. Only the placeholder file `config/wiki-target.example.json` belongs in git.

Requires `lark-cli` logged in as a user with wiki and docs scopes.

See the design note at [`docs/work-document-to-feishu.md`](../../docs/work-document-to-feishu.md).
