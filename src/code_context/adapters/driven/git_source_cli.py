"""GitCliSource — subprocess to `git` with ASCII unit-separator parsing."""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from code_context.domain.models import Change, DiffFile

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

    def diff_files(self, root: Path, ref: str) -> list[DiffFile]:
        """Use git diff-tree + numstat-like parsing to get hunks per file.

        Strategy: `git diff <ref>^! --unified=0 --no-color` gives a unified
        diff with zero context lines. Each hunk header line is:
            @@ -<old_start>,<old_count> +<new_start>,<new_count> @@
        We parse those into (new_start, new_start + new_count - 1) pairs.

        For ref == HEAD, the worktree diff (uncommitted changes) is excluded;
        we always show the committed diff. To diff worktree, the caller would
        pass an explicit ref like "HEAD" with a different strategy — out of
        scope for v0.7.0.
        """
        if not self.is_repo(root):
            return []

        # ^! syntax means "this commit's changes vs its parent". Equivalent to
        # `git diff <ref>~1 <ref>` for non-merge commits. For the initial
        # commit, ^! is invalid; fall back to `git diff --root <ref>`.
        try:
            res = subprocess.run(
                ["git", "diff", f"{ref}^!", "--unified=0", "--no-color"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=True,
            )
            diff_text = res.stdout
        except subprocess.CalledProcessError:
            # Probably the initial commit. Try --root.
            try:
                res = subprocess.run(
                    ["git", "diff", "--root", "--unified=0", "--no-color", ref],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                diff_text = res.stdout
            except subprocess.CalledProcessError as exc:
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
