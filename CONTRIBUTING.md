# Contributing

Thanks for considering a contribution to `code-context`.

## Local setup

```bash
git clone https://github.com/nachogeinfor-ops/code-context.git
cd code-context
python -m venv .venv
source .venv/bin/activate          # Unix/macOS
# OR:
source .venv/Scripts/activate      # Git Bash on Windows
pip install -e .[dev]
```

## Running tests

```bash
pytest -v               # all tests
pytest tests/unit -v    # fast subset (<1s)
pytest tests/integration -v  # exercises real fs + git CLI (~10s)
pytest tests/contract -v     # fetches tool-protocol.md from context-template (network)
```

To run the contract test offline, point it at a local copy:

```bash
CC_CONTRACT_DOC=/path/to/tool-protocol.md pytest tests/contract -v
```

## Lint + format

```bash
ruff check src tests
ruff format src tests
```

## Adding a new port adapter

See [docs/extending.md](docs/extending.md). The TL;DR:

1. Implement the port (it's a Protocol — duck typing, no inheritance needed).
2. Add a unit test mocking dependencies.
3. Add a config knob if it should be selectable at runtime.
4. Wire it in `_composition.py`.

## Tool Protocol contract coupling

The 3 MCP tools we expose must match `context-template/docs/tool-protocol.md` byte-for-byte at the parameter level. The contract test verifies this. If you need to add a tool or change a parameter:

1. Open a PR against [`context-template`](https://github.com/nachogeinfor-ops/context-template) updating `docs/tool-protocol.md`.
2. Land that PR.
3. Open a PR here updating the registration in `src/code_context/adapters/driving/mcp_server.py`.
4. Both PRs must be merged together (or in close succession).

## PR checklist

- [ ] Tests pass locally (`pytest -v`).
- [ ] Ruff lint + format clean.
- [ ] If you changed an MCP tool, the corresponding context-template PR is linked.
- [ ] Conventional Commits message.
