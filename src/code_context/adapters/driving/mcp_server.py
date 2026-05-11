"""MCP driving adapter: registers the 7 contract tools on an mcp Server."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from code_context._time_parse import InvalidSinceError, parse_since
from code_context.domain.use_cases.explain_diff import ExplainDiffUseCase
from code_context.domain.use_cases.find_definition import FindDefinitionUseCase
from code_context.domain.use_cases.find_references import FindReferencesUseCase
from code_context.domain.use_cases.get_file_tree import GetFileTreeUseCase
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
    find_definition: FindDefinitionUseCase,
    find_references: FindReferencesUseCase,
    get_file_tree: GetFileTreeUseCase,
    explain_diff: ExplainDiffUseCase,
) -> None:
    """Register the 7 contract tools on the given mcp Server instance."""

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
                            "description": (
                                "Cutoff for commits. Accepts ISO 8601 "
                                "('2026-05-08T00:00:00Z'), relative phrases "
                                "('4 hours ago', '2 weeks ago'), or keywords "
                                "('yesterday', 'today', 'last week'). "
                                "Defaults to 7 days ago when omitted."
                            ),
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
            Tool(
                name="find_definition",
                description=(
                    "Locate the definition site of a named symbol (function, class, "
                    "method, type, struct, enum, interface, record). Use this INSTEAD of "
                    'shelling out to grep when the user asks "where is X defined?" — '
                    "returns SymbolDef[] with path, line range, kind, and language. "
                    "Faster and more accurate than grepping for `def X` / `class X` / "
                    "`function X` / etc., because it consults a tree-sitter-indexed "
                    "symbol table built at reindex time, not the raw text."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact identifier to locate.",
                        },
                        "language": {
                            "type": "string",
                            "enum": [
                                "python",
                                "javascript",
                                "typescript",
                                "go",
                                "rust",
                                "csharp",
                            ],
                            "description": ("Optional language hint for same-name disambiguation."),
                        },
                        "max": {"type": "integer", "default": 5},
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="find_references",
                description=(
                    "List every textual occurrence of a named symbol in the indexed "
                    'corpus. Use INSTEAD of `grep -n "X"` when the user asks "who '
                    'calls X?" or "where is X used?". Returns SymbolRef[] with path, '
                    "line, snippet. Word-boundary matched, so 'log' won't return "
                    "'logger' or 'log_format'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact identifier to find references for.",
                        },
                        "max": {"type": "integer", "default": 50},
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="get_file_tree",
                description=(
                    "Repo-relative directory tree, gitignore-aware. Use INSTEAD of "
                    "shelling out to `Bash: ls -R` or `Bash: tree` when the user "
                    "asks for the project structure or for orientation in an "
                    "unfamiliar module. Returns a hierarchical FileTreeNode with "
                    "files (with byte sizes) and directories (with recursive "
                    "children, capped at max_depth). Honors .gitignore; skips "
                    "hidden files unless include_hidden=true."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": (
                                "Optional repo-relative subdirectory; defaults to root."
                            ),
                        },
                        "max_depth": {
                            "type": "integer",
                            "default": 4,
                            "description": "Cap on tree depth.",
                        },
                        "include_hidden": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include dot-files / dot-directories.",
                        },
                    },
                },
            ),
            Tool(
                name="explain_diff",
                description=(
                    "AST-aligned chunks affected by the diff at `ref`. Use INSTEAD "
                    'of `Bash: git show <sha>` when the user asks "what does this '
                    'commit do?" or "what changed in HEAD~3?". The chunker resolves '
                    "which whole functions / classes were touched, not just raw line "
                    "additions — much easier for an LLM to reason about. Returns "
                    "DiffChunk[] with path, lines, snippet, kind, and change "
                    '("added"|"modified"|"deleted").'
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": (
                                "Git ref: full SHA, short SHA, HEAD, HEAD~N, branch name."
                            ),
                        },
                        "max_chunks": {"type": "integer", "default": 50},
                    },
                    "required": ["ref"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        # Sprint 13.1: git-using handlers are async (asyncio.create_subprocess_exec)
        # and integrate with the Proactor event loop. They do NOT go through
        # asyncio.to_thread, which on Windows interacts badly with subprocess
        # invocation.
        if name == "recent_changes":
            return await _handle_recent(recent_changes, arguments)
        if name == "explain_diff":
            return await _handle_explain_diff(explain_diff, arguments)
        # CPU-bound or filesystem-walk handlers stay on to_thread to avoid
        # blocking the asyncio loop with potentially long synchronous work.
        if name == "search_repo":
            return await asyncio.to_thread(_handle_search, search_repo, arguments)
        if name == "get_summary":
            return await asyncio.to_thread(_handle_summary, get_summary, arguments)
        if name == "find_definition":
            return await asyncio.to_thread(_handle_find_definition, find_definition, arguments)
        if name == "find_references":
            return await asyncio.to_thread(_handle_find_references, find_references, arguments)
        if name == "get_file_tree":
            return await asyncio.to_thread(_handle_file_tree, get_file_tree, arguments)
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


async def _handle_recent(uc: RecentChangesUseCase, args: dict[str, Any]) -> list[TextContent]:
    since = None
    if args.get("since"):
        # Sprint 14: accept ISO format OR natural-language phrases like
        # "4 hours ago" / "yesterday" — the UX CLAUDE.md has documented since v1.
        try:
            since = parse_since(args["since"])
        except InvalidSinceError as exc:
            log.warning("recent_changes: bad since=%r — %s", args.get("since"), exc)
            return [
                TextContent(
                    type="text",
                    text=_to_json({"error": "invalid_since", "message": str(exc)}),
                )
            ]
    commits = await uc.run(
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


def _handle_find_definition(uc: FindDefinitionUseCase, args: dict[str, Any]) -> list[TextContent]:
    defs = uc.run(
        name=args["name"],
        language=args.get("language"),
        max_count=int(args.get("max", 5)),
    )
    payload = [
        {
            "name": d.name,
            "path": d.path,
            "lines": list(d.lines),
            "kind": d.kind,
            "language": d.language,
        }
        for d in defs
    ]
    return [TextContent(type="text", text=_to_json(payload))]


def _handle_find_references(uc: FindReferencesUseCase, args: dict[str, Any]) -> list[TextContent]:
    refs = uc.run(
        name=args["name"],
        max_count=int(args.get("max", 50)),
    )
    payload = [{"path": r.path, "line": r.line, "snippet": r.snippet} for r in refs]
    return [TextContent(type="text", text=_to_json(payload))]


def _handle_file_tree(uc: GetFileTreeUseCase, args: dict[str, Any]) -> list[TextContent]:
    tree = uc.run(
        path=args.get("path"),
        max_depth=int(args.get("max_depth", 4)),
        include_hidden=bool(args.get("include_hidden", False)),
    )
    payload = _serialize_tree_node(tree)
    return [TextContent(type="text", text=_to_json(payload))]


def _serialize_tree_node(node) -> dict[str, Any]:
    """Recursively flatten a FileTreeNode tuple to plain JSON dicts."""
    out: dict[str, Any] = {
        "path": node.path,
        "kind": node.kind,
        "size": node.size,
        "children": [_serialize_tree_node(c) for c in node.children],
    }
    return out


async def _handle_explain_diff(uc: ExplainDiffUseCase, args: dict[str, Any]) -> list[TextContent]:
    chunks = await uc.run(
        ref=args["ref"],
        max_chunks=int(args.get("max_chunks", 50)),
    )
    payload = [
        {
            "path": c.path,
            "lines": list(c.lines),
            "snippet": c.snippet,
            "kind": c.kind,
            "change": c.change,
        }
        for c in chunks
    ]
    return [TextContent(type="text", text=_to_json(payload))]


def _to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
