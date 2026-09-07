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
