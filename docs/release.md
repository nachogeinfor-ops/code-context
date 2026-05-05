# Releasing code-context

How to cut a release of `code-context` and publish it to PyPI.

## One-time setup (PyPI Trusted Publisher)

Trusted Publisher means PyPI accepts uploads from this GitHub repo
based on an OIDC token, not a long-lived API key. Zero secrets to
manage; rotate-by-not-rotating.

1. **Have a PyPI account.** Either the org's `nachogeinfor-ops`
   account or a personal account that owns the `code-context-mcp`
   project name. The first manual upload of a brand-new project
   name has to come from a logged-in account; from then on, the
   GitHub Actions workflow takes over.

   The unhyphenated `code-context` PyPI name is squatted by an
   abandoned 2023 project; we publish under `code-context-mcp`
   instead. The Python module, CLI binaries, and GitHub repo are
   all still `code-context` / `code_context`. See
   [`v1-api.md`](v1-api.md#names-at-a-glance) for the full naming
   table.

2. **Register the Trusted Publisher** at
   https://pypi.org/manage/account/publishing/ (you must be logged
   in to the same account that owns / will own the project). Fill
   in:
   - **PyPI Project Name**: `code-context-mcp`
   - **Owner**: `nachogeinfor-ops`
   - **Repository name**: `code-context`
   - **Workflow filename**: `release.yml`
   - **Environment name**: `release`

3. **Create the GitHub environment** at `Settings → Environments
   → New environment` named exactly `release`. No required reviewers
   needed (the tag itself is the gate); leave protection rules off
   unless you want a manual approval step before each publish.

After this, every `git tag vX.Y.Z && git push origin vX.Y.Z`
triggers `.github/workflows/release.yml` which builds the dists,
runs `twine check`, and uploads to PyPI via OIDC. No secrets to
rotate.

## Per-release checklist

1. Run the per-sprint verification from
   [`../docs/superpowers/plans/2026-05-04-context-engine-roadmap.md`](../docs/superpowers/plans/2026-05-04-context-engine-roadmap.md):
   green tests, lint, format, smoke against `WinServiceScheduler`.
2. Bump `pyproject.toml`'s `version` and
   `src/code_context/__init__.py`'s `__version__` to the new
   number.
3. Add a `## vX.Y.Z — YYYY-MM-DD` section to
   [`../CHANGELOG.md`](../CHANGELOG.md). Recap behavior changes,
   tests, and any affected versions.
4. Commit: `chore(release): bump to vX.Y.Z + changelog`.
5. Annotated tag with the changelog body:
   ```bash
   git tag -a vX.Y.Z -F <(awk '/^## vX.Y.Z/,/^## /' CHANGELOG.md | head -n -1)
   ```
   Or paste the body into a `-m` heredoc (see prior tags for the
   pattern).
6. `git push origin main vX.Y.Z`.
7. Watch
   [`Actions → Release`](https://github.com/nachogeinfor-ops/code-context/actions/workflows/release.yml).
   The `build` job produces `code_context-X.Y.Z-py3-none-any.whl`
   and `code_context-X.Y.Z.tar.gz`; the `publish` job uploads them
   to PyPI.
8. Verify https://pypi.org/project/code-context-mcp/ shows the
   new version (refresh after a few seconds).
9. Create the GitHub release:
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-from-tag
   ```
10. Announce: cross-link `context-template`'s tool-protocol release
    if the same sprint touched it.

## Failure modes

- **Trusted Publisher rejected with `invalid_grant`**: the workflow
  filename or environment name doesn't match the PyPI registration.
  Fix the registration; re-tagging won't re-publish — bump patch
  (`vX.Y.Z+1`) and re-tag.
- **`twine check` fails in CI**: README or CHANGELOG has a markdown
  issue PyPI's renderer rejects. Reproduce locally with:
  ```bash
  python -m build
  twine check dist/*
  ```
  Fix and re-tag (with a bumped patch).
- **Wheel doesn't include data files**: pyproject's
  `[tool.setuptools.packages.find]` should pick up everything under
  `src/`. If a tree-sitter grammar binary or similar gets missed,
  add a `MANIFEST.in` with `recursive-include src/code_context *`.
- **`build` job fails on a PR**: it shouldn't — `release.yml` only
  fires on `v*` tag pushes. If you see it, check `on.push.tags` in
  the workflow.
- **PyPI is down / slow**: the `pypa/gh-action-pypi-publish` action
  retries automatically. Re-running the workflow from the Actions
  tab is safe (PyPI rejects duplicate version uploads).

## Yanking a release

If a published version turns out to have a critical bug:

1. Bump patch, fix, re-release through the normal flow.
2. On PyPI's project page, mark the bad version as "yanked" with
   a reason. Yanking is preferred over deletion because it leaves
   the version reachable for anyone pinning it but stops new
   `pip install code-context-mcp` from picking it up.
3. Add a CHANGELOG note under the yanked version explaining what
   was broken and which version supersedes it.

## Version pairing with `context-template`

`code-context` implements the Tool Protocol defined in
[`context-template`](https://github.com/nachogeinfor-ops/context-template).
Each `code-context` MAJOR.MINOR pairs with a specific Tool Protocol
version:

| `code-context` | Tool Protocol | `context-template` |
|---|---|---|
| v0.5.x | v1.1 | v0.2.x |
| v0.6.x – v0.9.x | v1.2 | v0.3.x |
| v1.0.x (this release) | v1.2 | v0.3.x |

The contract test (`tests/contract/test_contract.py`) fetches the
upstream `tool-protocol.md` at CI time, so any drift surfaces as a
red CI run. When bumping the protocol version, the upstream PR
must merge first — otherwise the new `code-context` version's CI
fails on the contract test.
