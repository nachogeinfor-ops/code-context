"""GitCliSource — asyncio subprocess to `git` with ASCII unit-separator parsing."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from code_context.domain.models import Change, DiffFile

log = logging.getLogger(__name__)

_FS = "\x1f"  # ASCII unit separator
_PRETTY = f"%H{_FS}%aI{_FS}%an{_FS}%s"


class _GitFailed(RuntimeError):
    """Raised by _run_git when git exits non-zero."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"git exited {returncode}: {stderr.strip()[:200]}")
        self.returncode = returncode
        self.stderr = stderr


async def _run_git(argv: list[str], *, cwd: Path) -> tuple[str, str]:
    """Run `git <argv>` async, returning (stdout, stderr).

    Replaces subprocess.run because subprocess.run from inside an
    asyncio loop on Windows (Proactor IOCP) deadlocks. Decodes both
    streams as UTF-8 with errors='replace' for the same reason
    documented in the original adapter: git diff may emit mixed-
    encoding source bytes that crash strict decoders.

    Raises _GitFailed on non-zero exit.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_bytes, err_bytes = await proc.communicate()
    stdout = out_bytes.decode("utf-8", errors="replace")
    stderr = err_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise _GitFailed(proc.returncode or -1, stderr)
    return stdout, stderr


class GitCliSource:
    def is_repo(self, root: Path) -> bool:
        # Pure filesystem check; no subprocess, no asyncio interaction.
        return (root / ".git").exists()

    def head_sha(self, root: Path) -> str:
        """Sync because the only caller (IndexerUseCase, BackgroundIndexer)
        runs in sync contexts that pre-date the MCP request loop. Keeping
        it sync avoids forcing the entire indexer to become async without
        a real driver. The deadlock risk addressed by Sprint 13.1 only
        applies to handlers invoked from inside the stdio asyncio loop;
        head_sha is never called from there.
        """
        if not self.is_repo(root):
            return ""
        try:
            res = subprocess.run(  # noqa: S603 — argv is a fixed literal
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return (res.stdout or "").strip()
        except subprocess.CalledProcessError as exc:
            log.warning("git rev-parse HEAD failed: %s", exc)
            return ""

    async def commits(
        self,
        root: Path,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]:
        if not self.is_repo(root):
            return []

        argv = ["log", f"--pretty=format:{_PRETTY}", "--name-only", f"-{max_count}"]
        if since is not None:
            argv.append(f"--since={since.isoformat()}")
        if paths:
            argv.append("--")
            argv.extend(paths)

        try:
            stdout, _ = await _run_git(argv, cwd=root)
        except _GitFailed as exc:
            log.warning("git log failed: %s", exc)
            return []

        return _parse(stdout)

    async def diff_files(self, root: Path, ref: str) -> list[DiffFile]:
        """Same strategy as before: try `git diff <ref>^! --unified=0`,
        fall back to `git diff --root <ref>` for the initial commit.
        Critical Windows note retained: utf-8 decoding with errors=replace
        because git diff output may contain mixed-encoding source bytes.
        """
        if not self.is_repo(root):
            return []

        try:
            diff_text, _ = await _run_git(
                ["diff", f"{ref}^!", "--unified=0", "--no-color"], cwd=root
            )
        except _GitFailed:
            # Probably the initial commit. Fall back to --root.
            try:
                diff_text, _ = await _run_git(
                    ["diff", "--root", "--unified=0", "--no-color", ref], cwd=root
                )
            except _GitFailed as exc:
                log.warning("git diff failed for ref %r: %s", ref, exc)
                return []

        return _parse_diff(diff_text)


def _parse(stdout: str) -> list[Change]:
    """Parse the formatted output into Change objects.

    Each commit is:
        <sha>\\x1f<iso_date>\\x1f<author>\\x1f<subject>\\n
        <path1>\\n
        <path2>\\n
        ...
        \\n  (blank separator)
    """
    commits: list[Change] = []
    blocks = [b for b in stdout.split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        header = lines[0]
        parts = header.split(_FS)
        if len(parts) < 4:
            continue
        sha, iso_date, author, summary = parts[0], parts[1], parts[2], parts[3]
        path_lines = [p.strip() for p in lines[1:] if p.strip()]
        try:
            date = datetime.fromisoformat(iso_date)
        except ValueError:
            continue
        commits.append(
            Change(
                sha=sha,
                date=date,
                author=author,
                paths=path_lines,
                summary=summary,
            )
        )
    return commits


def _parse_diff(diff_text: str) -> list[DiffFile]:
    """Parse a unified diff into a list of (path, hunks) pairs.

    Hunk headers look like:
        @@ -<old>,<oc> +<new>,<nc> @@

    File headers look like:
        diff --git a/<path> b/<path>
        +++ b/<path>

    We use the +++ header for the "new file" path; a/<path> would point
    at the old name in renames.
    """
    files_to_hunks: dict[str, list[tuple[int, int]]] = {}
    current_path: str | None = None
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    plus_path_re = re.compile(r"^\+\+\+ b/(.+)$")
    null_path_re = re.compile(r"^\+\+\+ /dev/null")

    for line in diff_text.splitlines():
        m = plus_path_re.match(line)
        if m:
            current_path = m.group(1)
            files_to_hunks.setdefault(current_path, [])
            continue
        if null_path_re.match(line):
            current_path = None  # File deletion — no new-file hunks.
            continue
        m = hunk_re.match(line)
        if m and current_path:
            new_start = int(m.group(1))
            new_count = int(m.group(2)) if m.group(2) else 1
            # new_count == 0 means pure deletion — use the surrounding line
            # as a single-line range.
            end_line = new_start if new_count == 0 else new_start + new_count - 1
            files_to_hunks[current_path].append((new_start, end_line))

    return [DiffFile(path=p, hunks=tuple(h)) for p, h in files_to_hunks.items()]
