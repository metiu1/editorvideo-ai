# Contributing

Thanks for taking a look. Issues and pull requests are welcome — bug reports with a project
`.json` and the ffmpeg command line from the error are the most useful kind.

## Setup

```bash
git clone https://github.com/metiu1/editorvideo-ai.git
cd editorvideo-ai
python scripts/setup.py
```

One command: dependencies, compiled web interface, MCP server registration, `vedit doctor`
and the fast tests. `--json` gives a machine-readable result if an agent is doing this.

## Ground rules

- **Every project change goes through `Store`.** The UI, the chat assistant and the MCP agent
  all call the same methods; never write into the document from `api.py`, `mcp_server.py` or
  `cli.py`.
- Code, comments and user-facing messages are **in Italian**, like the rest of the project.
  `README.md` (English, also the PyPI page) and this file are the exception; the Italian
  README is `README.it.md`.
- New effect → `effects.py`. New MCP tool → a method in `store.py`, a wrapper in
  `mcp_server.py`, a test in `tests/test_mcp.py`. UI change → `npm run build`.
- No new dependencies without a reason. The core stands on ffmpeg, the standard library,
  `numpy` and Pillow.
- Every new behaviour comes with a test; real renders go behind the `slow` marker.

## Before opening a PR

```bash
pytest -m "not slow"          # plus the part of `slow` your change touches
cd frontend && npm test       # if you changed the UI
```

The full contract for humans and coding agents alike is [`AGENTS.md`](AGENTS.md).
