"""GitCliSource — subprocess to `git` with ASCII unit-separator parsing."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from code_context.domain.models import Change

log = logging.getLogger(__name__)

_FS = "\x1f"  # ASCII unit separator
_PRETTY = f"%H{_FS}%aI{_FS}%an{_FS}%s"


class GitCliSource:
    def is_repo(self, root: Path) -> bool:
        return (root / ".git").exists()

    def head_sha(self, root: Path) -> str:
        if not self.is_repo(root):
            return ""
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            return out.stdout.strip()
        except subprocess.CalledProcessError as exc:
            log.warning("git rev-parse HEAD failed: %s", exc)
            return ""

    def commits(
        self,
        root: Path,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]:
        if not self.is_repo(root):
            return []

        cmd = ["git", "log", f"--pretty=format:{_PRETTY}", "--name-only", f"-{max_count}"]
        if since is not None:
            cmd.append(f"--since={since.isoformat()}")
        if paths:
            cmd.append("--")
            cmd.extend(paths)

        try:
            res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            log.warning("git log failed: %s", exc)
            return []

        return _parse(res.stdout)


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
