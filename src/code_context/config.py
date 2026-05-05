"""Configuration: env vars + defaults, frozen dataclass."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

_DEFAULT_EXTENSIONS = [
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".cs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".md",
    ".yaml",
    ".yml",
    ".json",
]


@dataclass(frozen=True, slots=True)
class Config:
    repo_root: Path
    embeddings_provider: str  # "local" or "openai"
    embeddings_model: str | None
    openai_api_key: str | None
    include_extensions: list[str]
    max_file_bytes: int
    cache_dir: Path
    log_level: str
    top_k_default: int
    chunk_lines: int
    chunk_overlap: int
    chunker_strategy: str  # "treesitter" (default) or "line"
    keyword_strategy: str  # "sqlite" (default) or "none"
    rerank: bool
    rerank_model: str | None
    symbol_index_strategy: str  # "sqlite" (default) or "none"
    trust_remote_code: bool  # Off by default. Required for some HF models that ship custom Python.

    def repo_cache_subdir(self) -> Path:
        """Cache subdir specific to this repo (hashed for collision safety)."""
        h = hashlib.sha256(str(self.repo_root.resolve()).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / h


def load_config(default_repo_root: Path | None = None) -> Config:
    repo_root = Path(os.environ.get("CC_REPO_ROOT") or default_repo_root or Path.cwd())
    embeddings = os.environ.get("CC_EMBEDDINGS", "local")

    default_model = "all-MiniLM-L6-v2" if embeddings == "local" else "text-embedding-3-small"
    model = os.environ.get("CC_EMBEDDINGS_MODEL", default_model)

    cache_override = os.environ.get("CC_CACHE_DIR")
    cache_dir = (
        Path(cache_override)
        if cache_override
        else Path(platformdirs.user_cache_dir("code-context"))
    )

    exts_raw = os.environ.get("CC_INCLUDE_EXTENSIONS")
    if exts_raw:
        exts = [
            e.strip() if e.startswith(".") else f".{e.strip()}"
            for e in exts_raw.split(",")
            if e.strip()
        ]
    else:
        exts = list(_DEFAULT_EXTENSIONS)

    return Config(
        repo_root=repo_root.resolve(),
        embeddings_provider=embeddings,
        embeddings_model=model,
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        include_extensions=exts,
        max_file_bytes=int(os.environ.get("CC_MAX_FILE_BYTES", "1048576")),
        cache_dir=cache_dir,
        log_level=os.environ.get("CC_LOG_LEVEL", "INFO"),
        top_k_default=int(os.environ.get("CC_TOP_K_DEFAULT", "5")),
        chunk_lines=int(os.environ.get("CC_CHUNK_LINES", "50")),
        chunk_overlap=int(os.environ.get("CC_CHUNK_OVERLAP", "10")),
        chunker_strategy=os.environ.get("CC_CHUNKER", "treesitter"),
        keyword_strategy=os.environ.get("CC_KEYWORD_INDEX", "sqlite"),
        rerank=os.environ.get("CC_RERANK", "off").lower() in ("on", "true", "1"),
        rerank_model=os.environ.get("CC_RERANK_MODEL"),
        symbol_index_strategy=os.environ.get("CC_SYMBOL_INDEX", "sqlite"),
        trust_remote_code=os.environ.get("CC_TRUST_REMOTE_CODE", "off").lower()
        in ("on", "true", "1"),
    )
