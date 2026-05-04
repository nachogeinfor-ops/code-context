"""MCP driving adapter: registers the 3 contract tools on an mcp Server."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from code_context.domain.use_cases.get_summary import GetSummaryUseCase
from code_context.domain.use_cases.recent_changes import RecentChangesUseCase
from code_context.domain.use_cases.search_repo import SearchRepoUseCase

log = logging.getLogger(__name__)


def register(
    server: Server,
    *,
    search_repo: SearchRepoUseCase,
    recent_changes: RecentChangesUseCase,
    get_summary: GetSummaryUseCase,
) -> None:
    """Register the 3 contract tools on the given mcp Server instance."""

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_repo",
                description=(
                    "Semantic search over the indexed codebase. Use this INSTEAD of Grep "
                    "when the query is conceptual (e.g. 'where do we validate input', "
                    "'how is caching implemented', 'authentication flow'). Returns ranked "
                    "code fragments with file path, line range, snippet, score and a "
                    "one-line `why` excerpt. For exact-string lookup, Grep is still better."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "scope": {
                            "type": "string",
                            "description": (
                                "Optional repo-relative path prefix to constrain results."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="recent_changes",
                description=(
                    "Recent git commits with structured fields (sha, ISO date, author, "
                    "paths, summary). Use INSTEAD of `git log` shell calls — the output "
                    "is already parsed and filterable by `since` and `paths`. Defaults "
                    "to the last 7 days when `since` is omitted."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "since": {
                            "type": "string",
                            "description": "ISO 8601 cutoff; defaults to 7 days ago.",
                        },
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "max": {"type": "integer", "default": 20},
                    },
                },
            ),
            Tool(
                name="get_summary",
                description=(
                    "Structured snapshot of the project or a module: name, purpose "
                    "(README first paragraph), stack (Python/Node/Rust/Go/Java), "
                    "entry_points, key_modules, stats (files, loc, languages). Useful "
                    "at session start for orientation; prefer it over reading "
                    "README/CLAUDE.md when you need machine-readable fields."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["project", "module"]},
                        "path": {
                            "type": "string",
                            "description": "Required when scope='module'; repo-relative path.",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "search_repo":
            return await asyncio.to_thread(_handle_search, search_repo, arguments)
        if name == "recent_changes":
            return await asyncio.to_thread(_handle_recent, recent_changes, arguments)
        if name == "get_summary":
            return await asyncio.to_thread(_handle_summary, get_summary, arguments)
        raise ValueError(f"unknown tool: {name}")


def _handle_search(uc: SearchRepoUseCase, args: dict[str, Any]) -> list[TextContent]:
    results = uc.run(
        query=args["query"],
        top_k=int(args.get("top_k", 5)),
        scope=args.get("scope"),
    )
    payload = [
        {
            "path": r.path,
            "lines": list(r.lines),
            "snippet": r.snippet,
            "score": r.score,
            "why": r.why,
        }
        for r in results
    ]
    return [TextContent(type="text", text=_to_json(payload))]


def _handle_recent(uc: RecentChangesUseCase, args: dict[str, Any]) -> list[TextContent]:
    since = None
    if args.get("since"):
        since = datetime.fromisoformat(args["since"])
    commits = uc.run(
        since=since,
        paths=args.get("paths"),
        max_count=int(args.get("max", 20)),
    )
    payload = [
        {
            "sha": c.sha,
            "date": c.date.isoformat(),
            "author": c.author,
            "paths": c.paths,
            "summary": c.summary,
        }
        for c in commits
    ]
    return [TextContent(type="text", text=_to_json(payload))]


def _handle_summary(uc: GetSummaryUseCase, args: dict[str, Any]) -> list[TextContent]:
    scope = args.get("scope", "project")
    path = Path(args["path"]) if args.get("path") else None
    summary = uc.run(scope=scope, path=path)
    payload = {
        "name": summary.name,
        "purpose": summary.purpose,
        "stack": summary.stack,
        "entry_points": summary.entry_points,
        "key_modules": summary.key_modules,
        "stats": summary.stats,
    }
    return [TextContent(type="text", text=_to_json(payload))]


def _to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
