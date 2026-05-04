"""RecentChangesUseCase — direct delegation to GitSource with no-repo fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from code_context.domain.models import Change
from code_context.domain.ports import GitSource

log = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_DAYS = 7


@dataclass
class RecentChangesUseCase:
    git_source: GitSource
    repo_root: Path

    def run(
        self,
        since: datetime | None = None,
        paths: list[str] | None = None,
        max_count: int = 20,
    ) -> list[Change]:
        if not self.git_source.is_repo(self.repo_root):
            log.warning("recent_changes: %s is not a git repo; returning []", self.repo_root)
            return []
        if since is None:
            since = datetime.now(UTC) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        return self.git_source.commits(
            self.repo_root, since=since, paths=paths, max_count=max_count
        )
