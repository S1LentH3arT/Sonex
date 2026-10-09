# sonex-agent

Install the terminal music agent with:

```bash
npm install -g sonex-agent@alpha
sonex
```

The first `sonex` launch provisions a private Python 3.12 runtime under
`~/.sonex/runtime`. User credentials and application state remain under
`SONEX_HOME` (default: `~/.sonex`). The alpha package supports Linux and WSL2.

For source development, use the repository installer from the project root:
`./scripts/install.sh`.

Scriptable read-only commands are also available:

```bash
sonex status --json
sonex auth list --json
sonex extension list --json
sonex sandbox status --json
sonex model list --json
sonex memory search <query> --json
sonex search <query> --provider current --json
sonex recent --provider current --json
sonex playlist list --json
sonex playlist show <name> --json
```

Use `sonex auth login <provider>` for credentials. API keys are read from a
hidden prompt, `SONEX_<PROVIDER>_API_KEY`, or stdin; they are not accepted as
command-line arguments.
